"""Persistent application state and event logging."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.paths import LOG_PATH, ensure_project_layout


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def log_event(event: str, details: str = "") -> None:
    ensure_project_layout()
    new_file = not LOG_PATH.exists()
    with LOG_PATH.open("a", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file, delimiter=";")
        if new_file:
            writer.writerow(["Время", "Событие", "Подробности"])
        writer.writerow([datetime.now().astimezone().isoformat(timespec="seconds"), event, details])
