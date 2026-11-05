"""Application entry point and process singleton management."""
from __future__ import annotations

import os
import sys

from src.config_manager import load_config
from src.paths import LOCK_PATH, STOP_REQUEST_PATH, ensure_project_layout
from src.startup import install_startup, uninstall_startup
from src.steam_focus_guard import SteamFocusGuard, psutil


def main() -> int:
    ensure_project_layout()
    args = set(sys.argv[1:])
    if "--install-startup" in args:
        return install_startup()
    if "--uninstall-startup" in args:
        return uninstall_startup()
    if "--stop" in args:
        STOP_REQUEST_PATH.write_text("stop", encoding="utf-8")
        config, _ = load_config()
        print(config["ui"]["stop_requested"])
        return 0
    if os.name != "nt":
        print("Этот скрипт рассчитан на Windows.")
        return 1
    if psutil is None:
        config, _ = load_config()
        print(config["ui"]["dependency_missing"])
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
        config, _ = load_config()
        print(config["ui"]["already_running"])
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
