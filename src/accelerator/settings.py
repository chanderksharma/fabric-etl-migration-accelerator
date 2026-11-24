"""Runtime configuration read once from the environment, plus structured logging setup."""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from etl_migration_core.plugins import plugin_allowlist_from_environment

DEFAULT_STATE_DIR = Path(".accelerator")
DEFAULT_ARTIFACT_DIR = Path("generated-fabric-workflows")
DEFAULT_ALLOWED_HOSTS: tuple[str, ...] = ("127.0.0.1", "localhost")
DEFAULT_WORKER_CONCURRENCY = 2
MAX_WORKER_CONCURRENCY = 16
DeploymentMode = Literal["local", "desktop", "server"]
LogFormat = Literal["text", "json"]
_VALID_DEPLOYMENT_MODES: frozenset[str] = frozenset({"local", "desktop", "server"})
_VALID_LOG_FORMATS: frozenset[str] = frozenset({"text", "json"})
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOGGER_ROOTS = (
    "accelerator",
    "etl_migration_core",
    "etl_portfolio_assessment",
    "etl_target_fabric",
)
_HANDLED_LOGGERS: dict[str, logging.Handler] = {}
_LOG_CONTEXT: ContextVar[dict[str, str] | None] = ContextVar(
    "accelerator_log_context", default=None
)


def _setting(env: Mapping[str, str], name: str) -> str | None:
    return (env.get(name) or "").strip() or None


def _parse_bool(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    normalized = raw.casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean setting value: {raw!r}")


def _parse_hosts(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return DEFAULT_ALLOWED_HOSTS
    hosts = tuple(token.strip().casefold() for token in raw.split(",") if token.strip())
    if not hosts:
        return DEFAULT_ALLOWED_HOSTS
    return hosts


def _parse_mode(raw: str | None) -> DeploymentMode:
    mode = (raw or "local").casefold()
    if mode not in _VALID_DEPLOYMENT_MODES:
        raise ValueError("ACCELERATOR_MODE must be one of: local, desktop, server")
    return mode  # type: ignore[return-value]


def _parse_log_format(raw: str | None) -> LogFormat:
    fmt = (raw or "text").casefold()
    if fmt not in _VALID_LOG_FORMATS:
        raise ValueError("ACCELERATOR_LOG_FORMAT must be one of: text, json")
    return fmt  # type: ignore[return-value]


def _parse_worker_concurrency(raw: str | None) -> int:
    if raw is None:
        return DEFAULT_WORKER_CONCURRENCY
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError("ACCELERATOR_WORKER_CONCURRENCY must be an integer") from error
    if not 1 <= value <= MAX_WORKER_CONCURRENCY:
        raise ValueError(
            f"ACCELERATOR_WORKER_CONCURRENCY must be between 1 and {MAX_WORKER_CONCURRENCY}"
        )
    return value


def current_log_context() -> dict[str, str]:
    """Return a copy of active correlation fields bound to the current execution context."""
    active = _LOG_CONTEXT.get()
    return dict(active) if active else {}


@contextmanager
def bind_log_context(**fields: str | None) -> Iterator[None]:
    """Bind correlation identifiers (e.g. request_id, run_id) for structured logs."""
    merged = current_log_context()
    for key, value in fields.items():
        if value is not None and value.strip():
            merged[key] = value.strip()
    token = _LOG_CONTEXT.set(merged)
    try:
        yield
    finally:
        _LOG_CONTEXT.reset(token)


@dataclass(frozen=True, slots=True)
class Settings:
    """Deployment-independent settings shared by the CLI, API, and desktop shell."""

    state_dir: Path = DEFAULT_STATE_DIR
    artifact_dir: Path = DEFAULT_ARTIFACT_DIR
    plugin_allowlist: frozenset[str] | None = None
    log_level: str = "INFO"
    log_format: LogFormat = "text"
    worker_concurrency: int = DEFAULT_WORKER_CONCURRENCY
    deployment_mode: DeploymentMode = "local"
    allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS
    allow_local_filesystem: bool = True
    api_bearer_token: str | None = None
    desktop_token: str | None = None
    dev_workspace_id: str | None = None

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Read ``ACCELERATOR_*`` variables; blank values mean unset."""
        env = os.environ if environ is None else environ
        mode = _parse_mode(_setting(env, "ACCELERATOR_MODE"))
        return cls(
            state_dir=Path(_setting(env, "ACCELERATOR_STATE_DIR") or DEFAULT_STATE_DIR),
            artifact_dir=Path(_setting(env, "ACCELERATOR_ARTIFACT_DIR") or DEFAULT_ARTIFACT_DIR),
            plugin_allowlist=plugin_allowlist_from_environment(env),
            log_level=(_setting(env, "ACCELERATOR_LOG_LEVEL") or "INFO").upper(),
            log_format=_parse_log_format(_setting(env, "ACCELERATOR_LOG_FORMAT")),
            worker_concurrency=_parse_worker_concurrency(
                _setting(env, "ACCELERATOR_WORKER_CONCURRENCY")
            ),
            deployment_mode=mode,
            allowed_hosts=_parse_hosts(_setting(env, "ACCELERATOR_ALLOWED_HOSTS")),
            allow_local_filesystem=_parse_bool(
                _setting(env, "ACCELERATOR_ALLOW_LOCAL_FILESYSTEM"),
                default=mode != "server",
            ),
            api_bearer_token=_setting(env, "ACCELERATOR_API_TOKEN"),
            desktop_token=_setting(env, "ACCELERATOR_DESKTOP_TOKEN"),
            dev_workspace_id=(
                _setting(env, "FABRIC_WORKSPACE_ID")
                or _setting(env, "ACCELERATOR_DEV_WORKSPACE")
            ),
        )


class _JsonLogFormatter(logging.Formatter):
    """Emit structured single-line JSON log records with active correlation context."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        context = current_log_context()
        if context:
            payload.update(context)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


class _StderrHandler(logging.Handler):
    """Write to whatever ``sys.stderr`` is at emit time, so redirected streams never go stale."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stderr.write(self.format(record) + "\n")
        except Exception:  # noqa: BLE001 - a handler must never raise into the caller
            self.handleError(record)


def configure_logging(settings: Settings) -> None:
    """Send the application loggers to stderr once, without touching the root logger."""
    level = logging.getLevelName(settings.log_level)
    if not isinstance(level, int):
        level = logging.INFO
    formatter: logging.Formatter = (
        _JsonLogFormatter()
        if settings.log_format == "json"
        else logging.Formatter(LOG_FORMAT)
    )
    for name in LOGGER_ROOTS:
        logger = logging.getLogger(name)
        logger.setLevel(level)
        handler = _HANDLED_LOGGERS.get(name)
        if handler is None:
            handler = _StderrHandler()
            logger.addHandler(handler)
            _HANDLED_LOGGERS[name] = handler
        handler.setFormatter(formatter)
