"""Shared pytest configuration."""

import pytest

AMBIENT_SETTINGS = (
    "ACCELERATOR_STATE_DIR",
    "ACCELERATOR_ARTIFACT_DIR",
    "ACCELERATOR_PLUGIN_ALLOWLIST",
    "ACCELERATOR_LOG_LEVEL",
)


@pytest.fixture(autouse=True)
def _isolate_accelerator_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a developer's shell configuration from changing where or how tests run."""
    for name in AMBIENT_SETTINGS:
        monkeypatch.delenv(name, raising=False)
