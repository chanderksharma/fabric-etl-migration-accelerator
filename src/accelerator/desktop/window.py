"""Windows desktop host for the local FastAPI and React application."""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import socket
import sys
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from http.client import HTTPResponse
from pathlib import Path
from threading import Thread
from types import TracebackType
from typing import IO, Self, cast
from urllib.request import Request, urlopen

APP_NAME = "Fabric ETL Migration Accelerator"
APP_FOLDER = "Fabric ETL Migration Accelerator"
DESKTOP_TOKEN_HEADER = "x-accelerator-desktop-token"
ASSET_PATTERN = re.compile(r'(?:src|href)="(/assets/[^"]+)"')


@dataclass(frozen=True)
class DesktopPaths:
    """Resolved per-user data and packaged UI paths."""

    root: Path
    state: Path
    artifacts: Path
    logs: Path
    webview: Path
    web_root: Path


def desktop_paths() -> DesktopPaths:
    """Resolve writable per-user directories and bundled React assets."""
    local_app_data = os.getenv("LOCALAPPDATA")
    root = (
        Path(local_app_data) / APP_FOLDER
        if local_app_data
        else Path.home() / ".fabric-etl-migration-accelerator"
    )
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    configured_web_root = os.getenv("ACCELERATOR_WEB_ROOT", "").strip()
    if configured_web_root:
        web_root = Path(configured_web_root)
    elif hasattr(sys, "_MEIPASS"):
        web_root = bundle_root / "apps" / "web" / "dist"
    else:
        packaged = Path(__file__).resolve().parents[1] / "web_dist"
        editable = Path(__file__).resolve().parents[3] / "apps" / "web" / "dist"
        cwd_dist = Path.cwd() / "apps" / "web" / "dist"
        if (packaged / "index.html").is_file():
            web_root = packaged
        elif (editable / "index.html").is_file():
            web_root = editable
        elif (cwd_dist / "index.html").is_file():
            web_root = cwd_dist
        elif (Path(__file__).resolve().parents[3] / "apps" / "web").is_dir():
            web_root = editable
        else:
            web_root = cwd_dist
    return DesktopPaths(
        root=root,
        state=root / "state",
        artifacts=root / "artifacts",
        logs=root / "logs",
        webview=root / "webview",
        web_root=web_root,
    )


def configure_desktop_environment(paths: DesktopPaths, token: str) -> None:
    """Set desktop-safe defaults before importing the FastAPI application."""
    for folder in (paths.state, paths.artifacts, paths.logs, paths.webview):
        folder.mkdir(parents=True, exist_ok=True)
    if not (paths.web_root / "index.html").is_file() or not (paths.web_root / "assets").is_dir():
        raise FileNotFoundError(
            "The analyst UI is not built. Run npm run build in apps\\web "
            "or rebuild the desktop app."
        )
    if not os.getenv("ACCELERATOR_STATE_DIR", "").strip():
        os.environ["ACCELERATOR_STATE_DIR"] = str(paths.state)
    if not os.getenv("ACCELERATOR_ARTIFACT_DIR", "").strip():
        os.environ["ACCELERATOR_ARTIFACT_DIR"] = str(paths.artifacts)
    os.environ["ACCELERATOR_WEB_ROOT"] = str(paths.web_root)
    os.environ["ACCELERATOR_DESKTOP_TOKEN"] = token


class SingleInstanceLock(AbstractContextManager["SingleInstanceLock"]):
    """Hold an operating-system file lock for one desktop process per user."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._stream: IO[bytes] | None = None

    def __enter__(self) -> Self:
        if os.name != "nt":
            raise RuntimeError("The desktop utility currently supports Windows only.")
        import msvcrt

        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            stream.close()
            raise RuntimeError(f"{APP_NAME} is already running for this user.") from error
        self._stream = stream
        return self

    def __exit__(
        self,
        _error_type: type[BaseException] | None,
        _error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        if self._stream is None:
            return
        import msvcrt

        self._stream.seek(0)
        try:
            msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self._stream.close()
            self._stream = None


class EmbeddedServer(AbstractContextManager["EmbeddedServer"]):
    """Run Uvicorn on a pre-bound random loopback port."""

    def __init__(self, token: str) -> None:
        import uvicorn

        from accelerator.server.api import app

        self.token = token
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(128)
        self.port = int(self.socket.getsockname()[1])
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=self.port,
            log_config=None,
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        self.thread = Thread(
            target=self.server.run,
            kwargs={"sockets": [self.socket]},
            name="accelerator-desktop-api",
        )

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> Self:
        self.thread.start()
        try:
            self.wait_until_ready()
        except Exception:
            self.server.should_exit = True
            self.thread.join(timeout=15)
            self.socket.close()
            raise
        return self

    def request(self, path: str) -> HTTPResponse:
        return cast(
            HTTPResponse,
            urlopen(
                Request(
                    self.base_url + path,
                    headers={DESKTOP_TOKEN_HEADER: self.token},
                ),
                timeout=10,
            ),
        )

    def wait_until_ready(self, timeout: float = 20) -> None:
        deadline = time.monotonic() + timeout
        last_error: OSError | None = None
        while time.monotonic() < deadline:
            if not self.thread.is_alive():
                raise RuntimeError("The embedded API stopped during startup.")
            try:
                with self.request("/health") as response:
                    payload = json.load(response)
                if payload.get("status") == "ok":
                    return
            except OSError as error:
                last_error = error
            time.sleep(0.05)
        raise TimeoutError("The embedded API did not become ready.") from last_error

    def verify_ui(self) -> None:
        """Verify the authenticated HTML and every referenced built asset."""
        with self.request("/") as response:
            html = response.read().decode("utf-8")
        if '<div id="root"></div>' not in html:
            raise RuntimeError("The embedded API did not serve the built analyst UI.")
        assets = ASSET_PATTERN.findall(html)
        if len(assets) < 2:
            raise RuntimeError("The desktop UI did not reference JavaScript and stylesheet assets.")
        for asset in assets:
            with self.request(asset) as response:
                if not response.read(1):
                    raise RuntimeError(f"Desktop UI asset is empty: {asset}")

    def __exit__(
        self,
        _error_type: type[BaseException] | None,
        _error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=15)
        self.socket.close()
        if self.thread.is_alive():
            raise RuntimeError("The embedded API did not stop cleanly.")


def _configure_logging(paths: DesktopPaths) -> None:
    logging.basicConfig(
        filename=paths.logs / "desktop.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )


def launch_desktop(*, debug: bool = False, smoke_test: bool = False) -> None:
    """Start the authenticated local API and show the native desktop window."""
    paths = desktop_paths()
    token = secrets.token_urlsafe(32)
    configure_desktop_environment(paths, token)
    _configure_logging(paths)
    with SingleInstanceLock(paths.root / "desktop.lock"), EmbeddedServer(token) as server:
        server.verify_ui()
        if smoke_test:
            return
        try:
            import webview
        except ImportError as error:
            raise RuntimeError(
                "Desktop dependencies are missing. Run uv sync --extra desktop --locked."
            ) from error
        webview.create_window(
            APP_NAME,
            f"{server.base_url}/?desktop_token={token}",
            width=1440,
            height=900,
            min_size=(1024, 700),
            background_color="#f5f7fb",
            confirm_close=True,
        )
        webview.start(
            gui="edgechromium",
            debug=debug,
            private_mode=True,
            storage_path=str(paths.webview),
        )


def show_desktop_error(message: str) -> None:
    """Display startup errors for a windowed packaged executable."""
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, APP_NAME, 0x10)
    else:
        print(message, file=sys.stderr)


def desktop_entry() -> int:
    """Run the packaged desktop entry point with a native failure dialog."""
    smoke_test = os.getenv("ACCELERATOR_DESKTOP_SMOKE_TEST") == "1"
    try:
        launch_desktop(
            debug=os.getenv("ACCELERATOR_DESKTOP_DEBUG") == "1",
            smoke_test=smoke_test,
        )
    except Exception as error:
        logging.getLogger(__name__).exception("Desktop startup failed")
        if smoke_test:
            print(str(error), file=sys.stderr)
        else:
            show_desktop_error(str(error))
        return 1
    return 0
