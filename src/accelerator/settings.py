"""Runtime configuration read once from the environment, plus logging setup."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from etl_migration_core.plugins import plugin_allowlist_from_environment

DEFAULT_STATE_DIR = Path(".accelerator")
DEFAULT_ARTIFACT_DIR = Path("generated-fabric-workflows")
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOGGER_ROOTS = (
    "accelerator",
    "etl_migration_core",
    "etl_portfolio_assessment",
    "etl_target_fabric",
)
_HANDLED_LOGGERS: set[str] = set()


def _setting(env: Mapping[str, str], name: str) -> str | None:
    return (env.get(name) or "").strip() or None


@dataclass(frozen=True, slots=True)
class Settings:
    """Deployment-independent settings shared by the CLI, API, and desktop shell."""

    state_dir: Path = DEFAULT_STATE_DIR
    artifact_dir: Path = DEFAULT_ARTIFACT_DIR
    plugin_allowlist: frozenset[str] | None = None
    log_level: str = "INFO"

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Read ``ACCELERATOR_*`` variables; blank values mean unset."""
        env = os.environ if environ is None else environ
        return cls(
            state_dir=Path(_setting(env, "ACCELERATOR_STATE_DIR") or DEFAULT_STATE_DIR),
            artifact_dir=Path(_setting(env, "ACCELERATOR_ARTIFACT_DIR") or DEFAULT_ARTIFACT_DIR),
            plugin_allowlist=plugin_allowlist_from_environment(env),
            log_level=(_setting(env, "ACCELERATOR_LOG_LEVEL") or "INFO").upper(),
        )


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
    for name in LOGGER_ROOTS:
        logger = logging.getLogger(name)
        logger.setLevel(level)
        if name not in _HANDLED_LOGGERS:
            handler = _StderrHandler()
            handler.setFormatter(logging.Formatter(LOG_FORMAT))
            logger.addHandler(handler)
            _HANDLED_LOGGERS.add(name)
