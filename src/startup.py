"""Windows startup registration helpers."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from src.config_manager import load_config
from src.paths import PROJECT_ROOT


def install_startup() -> int:
    if os.name != "nt":
        print("Автозапуск через реестр доступен только в Windows.")
        return 1
    import winreg
    python_path = Path(sys.executable)
    if python_path.name.lower() in {"python.exe", "python3.exe"}:
        pythonw = python_path.with_name("pythonw.exe")
        if pythonw.exists():
            python_path = pythonw
    entrypoint = PROJECT_ROOT / "main.py"
    command = f'"{python_path}" "{entrypoint}" --background'
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "SteamFocusGuard", 0, winreg.REG_SZ, command)
    config, _ = load_config()
    print(config["ui"]["startup_installed"])
    return 0


def uninstall_startup() -> int:
    if os.name != "nt":
        print("Автозапуск через реестр доступен только в Windows.")
        return 1
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        try:
            winreg.DeleteValue(key, "SteamFocusGuard")
        except FileNotFoundError:
            pass
    config, _ = load_config()
    print(config["ui"]["startup_removed"])
    return 0
