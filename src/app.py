"""Desktop application entry point and singleton management."""
from __future__ import annotations
import os
import sys
from src.config_manager import load_config
from src.paths import LOCK_PATH, STOP_REQUEST_PATH, ensure_project_layout
from src.steam_focus_guard import SteamFocusGuard, psutil

def main() -> int:
    ensure_project_layout()
    args = set(sys.argv[1:])
    if "--sync-websites" in args:
        from src.website_blocker_cli import main as sync_main
        return sync_main()
    if "--stop" in args:
        STOP_REQUEST_PATH.write_text("stop", encoding="utf-8")
        return 0
    if os.name != "nt":
        print("Focus Guard предназначен для Windows.")
        return 1
    if psutil is None:
        print("Не найден psutil. Установи зависимости приложения.")
        return 1
    lock_file = None
    try:
        import msvcrt
        lock_file = LOCK_PATH.open("a+")
        lock_file.seek(0)
        if lock_file.read(1) == "":
            lock_file.write("0")
            lock_file.flush()
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        print("Focus Guard уже запущен.")
        return 0
    except Exception:
        lock_file = None
    try:
        if STOP_REQUEST_PATH.exists():
            STOP_REQUEST_PATH.unlink()
    except OSError:
        pass
    try:
        app = SteamFocusGuard(background="--background" in args)
        app.run()
    finally:
        try:
            if lock_file:
                import msvcrt
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                lock_file.close()
        except Exception:
            pass
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
