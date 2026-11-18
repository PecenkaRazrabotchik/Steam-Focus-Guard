"""Windows startup registration helpers for source and frozen builds."""
from __future__ import annotations
import os
import sys
from pathlib import Path
from src.paths import PROJECT_ROOT

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "FocusGuard"

def install_startup() -> int:
    if os.name != "nt":
        raise OSError("Автозагрузка доступна только в Windows.")
    import winreg
    if getattr(sys, "frozen", False):
        command = f'"{Path(sys.executable).resolve()}" --background'
    else:
        python_path = Path(sys.executable)
        if python_path.name.lower() in {"python.exe", "python3.exe"}:
            pythonw = python_path.with_name("pythonw.exe")
            if pythonw.exists():
                python_path = pythonw
        command = f'"{python_path}" "{PROJECT_ROOT / "main.py"}" --background'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
    return 0

def uninstall_startup() -> int:
    if os.name != "nt":
        raise OSError("Автозагрузка доступна только в Windows.")
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        try:
            winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
    return 0
