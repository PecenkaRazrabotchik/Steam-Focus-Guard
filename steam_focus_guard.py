"""Backward-compatible launcher for existing BAT files and startup shortcuts."""

from src.steam_focus_guard import main


if __name__ == "__main__":
    raise SystemExit(main())
