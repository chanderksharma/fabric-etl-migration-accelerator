"""SQLite persistence for run state, derived results, caches, and retention."""

from __future__ import annotations

import shutil
import sqlite3
import time
import weakref
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import BaseModel

LATEST_SCHEMA_VERSION = 6
MAX_IDLE_CONNECTIONS = 8
CACHE_TOUCH_INTERVAL_SECONDS = 24 * 60 * 60
TERMINAL_STATUSES = ("completed", "failed", "cancelled")

CacheTable = Literal["cache", "ir_cache"]
_CACHE_VALUE_COLUMNS: dict[CacheTable, str] = {"cache": "result", "ir_cache": "package_json"}


class GarbageReport(BaseModel):
    """What a retention pass removed, or would remove when ``dry_run`` is true."""

    dry_run: bool
    runs_deleted: int = 0
    snapshots_deleted: int = 0
    publications_deleted: int = 0
    cache_rows_deleted: int = 0
    bytes_freed: int = 0


def _create_baseline(connection: sqlite3.Connection) -> None:
    """Schema 4 exactly as the last release created it.

    Databases in the field contain these tables and nothing else, so never edit this step:
    add a new one instead.
    """
    for statement in (
        "CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, preview TEXT NOT NULL)",
        """CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, snapshot TEXT NOT NULL, status TEXT NOT NULL,
            epoch INTEGER NOT NULL DEFAULT 0, lease REAL NOT NULL DEFAULT 0,
            processed INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL,
            cache_hits INTEGER NOT NULL DEFAULT 0, error TEXT, result TEXT
        )""",
        "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, result TEXT NOT NULL)",
        """CREATE TABLE IF NOT EXISTS capacity_inputs (
            run_id TEXT NOT NULL,
            workflow_path TEXT NOT NULL,
            input_json TEXT NOT NULL,
            PRIMARY KEY (run_id, workflow_path)
        )""",
        """CREATE TABLE IF NOT EXISTS capacity_settings (
            run_id TEXT PRIMARY KEY,
            settings_json TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS target_evaluations (
            run_id TEXT NOT NULL,
            platform_id TEXT NOT NULL,
            provider_version TEXT NOT NULL,
            evaluations_json TEXT NOT NULL,
            PRIMARY KEY (run_id, platform_id)
        )""",
        """CREATE TABLE IF NOT EXISTS neutral_assessments (
            run_id TEXT PRIMARY KEY,
            assessment_json TEXT NOT NULL
        )""",
    ):
        connection.execute(statement)


def _add_column(connection: sqlite3.Connection, table: str, definition: str) -> None:
    name = definition.split()[0]
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if name not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _add_ir_cache_and_retention(connection: sqlite3.Connection) -> None:
    """Add the canonical IR cache, then track run attempts and object age.

    Legacy rows start their retention clock now. The cache table is created here rather than
    in the baseline because released schema-4 databases do not have it.
    """
    connection.execute(
        """CREATE TABLE IF NOT EXISTS ir_cache (
            key TEXT PRIMARY KEY,
            package_json TEXT NOT NULL
        )"""
    )
    now = time.time()
    _add_column(connection, "runs", "attempts INTEGER NOT NULL DEFAULT 0")
    for table, column in (
        ("runs", "created_at"),
        ("snapshots", "created_at"),
        ("cache", "last_used"),
        ("ir_cache", "last_used"),
    ):
        _add_column(connection, table, f"{column} REAL NOT NULL DEFAULT 0")
        connection.execute(f"UPDATE {table} SET {column}=? WHERE {column}=0", (now,))
    connection.execute("CREATE INDEX IF NOT EXISTS runs_status ON runs (status)")


def _add_run_timings(connection: sqlite3.Connection) -> None:
    """Persist per-stage durations so slow runs can be explained after the fact."""
    _add_column(connection, "runs", "timings TEXT")


# Ordered, append-only. Each step is idempotent so a partially applied step can be retried,
# and a step that has shipped must never change: add a new one instead.
MIGRATIONS: tuple[tuple[int, Callable[[sqlite3.Connection], None]], ...] = (
    (4, _create_baseline),
    (5, _add_ir_cache_and_retention),
    (6, _add_run_timings),
)


def _close_connections(idle: list[sqlite3.Connection]) -> None:
    """Close every pooled handle; safe to call concurrently with the finalizer."""
    while True:
        try:
            connection = idle.pop()
        except IndexError:
            return
        connection.close()


class RunStore:
    """Thread-safe SQLite access with pooled connections and ordered schema migrations."""

    def __init__(self, root: Path, *, max_idle_connections: int = MAX_IDLE_CONNECTIONS) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.database = root / "runs.db"
        self._max_idle = max_idle_connections
        self._lock = RLock()
        self._idle: list[sqlite3.Connection] = []
        self._closed = False
        # Closes pooled handles when an unclosed store is garbage collected.
        weakref.finalize(self, _close_connections, self._idle)
        self._migrate()

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """Close idle connections; connections still checked out close on release."""
        with self._lock:
            self._closed = True
        _close_connections(self._idle)

    def _open(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _migrate(self) -> None:
        with closing(self._open()) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("BEGIN IMMEDIATE")
            try:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if not 0 <= version <= LATEST_SCHEMA_VERSION:
                    raise ValueError("Unsupported run database schema version")
                for target, migrate in MIGRATIONS:
                    if version < target:
                        migrate(connection)
                        connection.execute(f"PRAGMA user_version={target}")
                        version = target
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a pooled connection inside a transaction that commits or rolls back."""
        with self._lock:
            if self._closed:
                raise ValueError("Run store is closed")
            connection = self._idle.pop() if self._idle else None
        if connection is None:
            connection = self._open()
        try:
            with connection:
                yield connection
        except BaseException:
            connection.close()
            raise
        with self._lock:
            if not self._closed and len(self._idle) < self._max_idle:
                self._idle.append(connection)
                return
        connection.close()

    def cache_get(self, table: CacheTable, key: str) -> str | None:
        """Read one cached payload and refresh its age at most once per day."""
        column = _CACHE_VALUE_COLUMNS[table]
        now = time.time()
        with self.connection() as connection:
            row = connection.execute(
                f"SELECT {column} AS value, last_used FROM {table} WHERE key=?", (key,)
            ).fetchone()
            if row is None:
                return None
            if now - row["last_used"] > CACHE_TOUCH_INTERVAL_SECONDS:
                connection.execute(f"UPDATE {table} SET last_used=? WHERE key=?", (now, key))
        return str(row["value"])

    def cache_has(self, table: CacheTable, key: str) -> bool:
        """Check for a cached payload without reading it."""
        with self.connection() as connection:
            row = connection.execute(f"SELECT 1 FROM {table} WHERE key=?", (key,)).fetchone()
        return row is not None

    def cache_put(self, table: CacheTable, key: str, value: str) -> None:
        column = _CACHE_VALUE_COLUMNS[table]
        with self.connection() as connection:
            connection.execute(
                f"""INSERT INTO {table} (key, {column}, last_used) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    {column}=excluded.{column}, last_used=excluded.last_used""",
                (key, value, time.time()),
            )

    def collect_garbage(
        self, *, max_age_days: float, max_cache_bytes: int, dry_run: bool = False
    ) -> GarbageReport:
        """Remove aged terminal runs, unreferenced snapshots, publications, and cold cache rows.

        Runs that are queued or running, and every snapshot they reference, are always kept.
        """
        report = GarbageReport(dry_run=dry_run)
        cutoff = time.time() - max_age_days * 24 * 60 * 60
        with self.connection() as connection:
            if not dry_run:
                connection.execute("BEGIN IMMEDIATE")
            runs = connection.execute(
                "SELECT id, snapshot, status, created_at FROM runs"
            ).fetchall()
            expired = {
                row["id"]
                for row in runs
                if row["status"] in TERMINAL_STATUSES and row["created_at"] < cutoff
            }
            referenced = {row["snapshot"] for row in runs if row["id"] not in expired}
            old_snapshots = [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM snapshots WHERE created_at < ?", (cutoff,)
                )
                if row["id"] not in referenced
            ]
            cache_victims = self._cache_victims(connection, cutoff, max_cache_bytes)
            report.runs_deleted = len(expired)
            report.snapshots_deleted = len(old_snapshots)
            report.cache_rows_deleted = len(cache_victims)
            report.bytes_freed += sum(size for _table, _key, size in cache_victims)
            publications = [self.root / "publications" / run_id for run_id in sorted(expired)]
            report.publications_deleted = sum(path.is_dir() for path in publications)
            snapshot_dirs = [self.root / "snapshots" / snapshot_id for snapshot_id in old_snapshots]
            report.bytes_freed += sum(
                _tree_size(path) for path in (*publications, *snapshot_dirs) if path.is_dir()
            )
            if dry_run:
                return report
            for run_id in expired:
                for table in (
                    "capacity_inputs",
                    "capacity_settings",
                    "target_evaluations",
                    "neutral_assessments",
                ):
                    connection.execute(f"DELETE FROM {table} WHERE run_id=?", (run_id,))
                connection.execute("DELETE FROM runs WHERE id=?", (run_id,))
            for snapshot_id in old_snapshots:
                connection.execute("DELETE FROM snapshots WHERE id=?", (snapshot_id,))
            for table, key, _size in cache_victims:
                connection.execute(f"DELETE FROM {table} WHERE key=?", (key,))
        for path in (*publications, *snapshot_dirs):
            shutil.rmtree(path, ignore_errors=True)
        if expired or old_snapshots or cache_victims:
            self._compact()
        return report

    @staticmethod
    def _cache_victims(
        connection: sqlite3.Connection, cutoff: float, max_cache_bytes: int
    ) -> list[tuple[CacheTable, str, int]]:
        rows: list[tuple[float, CacheTable, str, int]] = []
        for table, column in _CACHE_VALUE_COLUMNS.items():
            rows.extend(
                (row["last_used"], table, row["key"], row["size"])
                for row in connection.execute(
                    f"SELECT key, LENGTH({column}) AS size, last_used FROM {table}"
                )
            )
        rows.sort(key=lambda item: item[0])
        total = sum(size for _used, _table, _key, size in rows)
        victims: list[tuple[CacheTable, str, int]] = []
        for used, table, key, size in rows:
            if used < cutoff or total > max_cache_bytes:
                victims.append((table, key, size))
                total -= size
        return victims

    def _compact(self) -> None:
        with closing(
            sqlite3.connect(self.database, timeout=30, isolation_level=None)
        ) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("VACUUM")


def _tree_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
