"""PyInstaller entry point for the Windows desktop utility."""

from accelerator.desktop import desktop_entry

if __name__ == "__main__":
    raise SystemExit(desktop_entry())
