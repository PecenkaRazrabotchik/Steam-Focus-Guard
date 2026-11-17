"""Task model and priority ordering for the desktop app."""
from __future__ import annotations

import re
import uuid
from typing import Any

FOCUS_LEVELS = {
    "main": {"label": "Главная", "color": "#3B82F6", "order": 0},
    "additional": {"label": "Дополнительная", "color": "#EAB308", "order": 1},
    "later": {"label": "Пока подождёт", "color": "#6B7280", "order": 2},
}


def normalize_task(raw: Any) -> dict[str, Any] | None:
    """Convert both new task objects and legacy text rows into the new schema."""
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        lowered = text.casefold()
        focus = "main" if lowered.startswith(("главное:", "главная:")) else (
            "additional" if lowered.startswith(("дополнительно", "по желанию")) else "later"
        )
        match = re.search(r"(\d+)\s*(?:-|–)?\s*\d*\s*мин", text, re.IGNORECASE)
        duration = int(match.group(1)) if match else 0
        text = re.sub(r"^(главное|главная|дополнительно|минимум|по желанию)\s*:\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"[,;]?\s*\d+\s*(?:-|–)?\s*\d*\s*минут(?:ы|а)?\s*$", "", text, flags=re.IGNORECASE).strip()
        return {"id": uuid.uuid4().hex, "focus": focus, "text": text or raw.strip(), "duration_minutes": duration}
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text", "")).strip()
    if not text:
        return None
    focus = str(raw.get("focus", "later"))
    if focus not in FOCUS_LEVELS:
        focus = "later"
    try:
        duration = max(0, min(24 * 60, int(raw.get("duration_minutes", 0))))
    except (TypeError, ValueError):
        duration = 0
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex),
        "focus": focus,
        "text": text,
        "duration_minutes": duration,
    }


def normalize_tasks(raw_tasks: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_tasks, list):
        return []
    tasks = [task for item in raw_tasks if (task := normalize_task(item)) is not None]
    return sort_tasks(tasks)


def sort_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep insertion order within each focus, but group tasks by priority."""
    indexed = list(enumerate(tasks))
    indexed.sort(key=lambda pair: (FOCUS_LEVELS.get(pair[1].get("focus"), FOCUS_LEVELS["later"])["order"], pair[0]))
    return [task for _, task in indexed]


def planned_minutes(tasks: list[dict[str, Any]]) -> int:
    return sum(max(0, int(task.get("duration_minutes", 0))) for task in tasks)
