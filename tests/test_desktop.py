"""Desktop host startup and storage contracts."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from accelerator.desktop.window import desktop_paths

ROOT = Path(__file__).parents[1]


def test_desktop_paths_use_local_app_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("ACCELERATOR_WEB_ROOT", str(tmp_path / "web"))

    paths = desktop_paths()

    assert paths.root == tmp_path / "Fabric ETL Migration Accelerator"
    assert paths.state == paths.root / "state"
    assert paths.artifacts == paths.root / "artifacts"
    assert paths.logs == paths.root / "logs"
    assert paths.web_root == tmp_path / "web"


def test_desktop_paths_falls_back_to_cwd_for_wheel_installs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import accelerator.desktop.window as window_module

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.delenv("ACCELERATOR_WEB_ROOT", raising=False)
    fake_site_pkg = tmp_path / "venv" / "Lib" / "site-packages" / "accelerator" / "desktop"
    fake_site_pkg.mkdir(parents=True)
    fake_window = fake_site_pkg / "window.py"
    fake_window.write_text("", encoding="utf-8")
    monkeypatch.setattr(window_module, "__file__", str(fake_window))

    repo_cwd = tmp_path / "workspace"
    cwd_dist = repo_cwd / "apps" / "web" / "dist"
    cwd_dist.mkdir(parents=True)
    (cwd_dist / "index.html").write_text("<div id='root'></div>", encoding="utf-8")
    monkeypatch.chdir(repo_cwd)

    paths = desktop_paths()
    assert paths.web_root == cwd_dist


def test_packaged_entry_smoke_starts_authenticated_ui_and_exits(
    tmp_path: Path,
) -> None:
    web_root = tmp_path / "web"
    assets = web_root / "assets"
    assets.mkdir(parents=True)
    (web_root / "index.html").write_text(
        '<div id="root"></div><script src="/assets/app.js"></script>'
        '<link rel="stylesheet" href="/assets/app.css">',
        encoding="utf-8",
    )
    (assets / "app.js").write_text("console.log('desktop smoke');", encoding="utf-8")
    (assets / "app.css").write_text("body{margin:0}", encoding="utf-8")
    environment = os.environ | {
        "LOCALAPPDATA": str(tmp_path / "local"),
        "ACCELERATOR_WEB_ROOT": str(web_root),
        "ACCELERATOR_DESKTOP_SMOKE_TEST": "1",
        "ACCELERATOR_STATE_DIR": "",
        "ACCELERATOR_ARTIFACT_DIR": "",
        "ACCELERATOR_DESKTOP_TOKEN": "",
    }

    result = subprocess.run(
        [sys.executable, "-m", "accelerator.desktop_entry"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    data_root = tmp_path / "local" / "Fabric ETL Migration Accelerator"
    assert (data_root / "state" / "runs.db").is_file()
    assert (data_root / "logs" / "desktop.log").is_file()
