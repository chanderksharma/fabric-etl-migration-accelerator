"""Validate active project runtime declarations."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_active_project_targets_only_python_313() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["requires-python"] == ">=3.13"
    assert pyproject["tool"]["ruff"]["target-version"] == "py313"
    assert pyproject["tool"]["mypy"]["python_version"] == "3.13"

    github_ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert 'python-version: "3.13"' in github_ci
    assert "3.12" not in github_ci

    azure_ci = (ROOT / "azure-pipelines.yml").read_text(encoding="utf-8")
    assert 'versionSpec: "3.13"' in azure_ci
    assert "3.12" not in azure_ci

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.13-slim" in dockerfile
