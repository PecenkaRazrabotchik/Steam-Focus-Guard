"""Steam executable discovery helpers."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def get_steam_executable(config: dict[str, Any], detected_path: str | None = None) -> Path | None:
    candidates: list[Path] = []
    configured = str(config.get("app", {}).get("steam_executable", "")).strip().strip('"')
    if configured:
        candidates.append(Path(os.path.expandvars(configured)))
    if detected_path:
        candidates.append(Path(detected_path))

    if os.name == "nt":
        try:
            import winreg
            registry_locations = (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamExe"),
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
            )
            for hive, subkey, value_name in registry_locations:
                try:
                    with winreg.OpenKey(hive, subkey) as key:
                        value, _ = winreg.QueryValueEx(key, value_name)
                    candidate = Path(value)
                    if candidate.is_dir():
                        candidate = candidate / "steam.exe"
                    candidates.append(candidate)
                except OSError:
                    continue
        except ImportError:
            pass

    candidates.extend([
        Path(r"C:\Program Files (x86)\Steam\steam.exe"),
        Path(r"C:\Program Files\Steam\steam.exe"),
    ])
    for candidate in candidates:
        try:
            if candidate.is_file() and candidate.name.lower() == "steam.exe":
                return candidate.resolve()
        except OSError:
            continue
    return None
