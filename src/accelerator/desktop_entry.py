"""Top-level Windows desktop PyInstaller entrypoint."""

from accelerator.desktop.window import desktop_entry

if __name__ == "__main__":
    raise SystemExit(desktop_entry())
