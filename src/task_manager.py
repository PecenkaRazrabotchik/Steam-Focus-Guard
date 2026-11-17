"""Task model, status/priority metadata and stable focus ordering."""
from __future__ import annotations
import re
import uuid
from typing import Any

FOCUS_LEVELS = {
    "main": {"label": "Главная", "color": "#3B82F6", "order": 0},
    "additional": {"label": "Дополнительная", "color": "#EAB308", "order": 1},
    "later": {"label": "Пока подождёт", "color": "#6B7280", "order": 2},
}
STATUS_LEVELS = {
    "todo": {"label": "К выполнению", "color": "#64748B"},
    "in_progress": {"label": "В работе", "color": "#3B82F6"},
    "done": {"label": "Выполнено", "color": "#16A34A"},
}
PRIORITY_LEVELS = {
    "urgent": {"label": "Срочно", "color": "#EF4444", "order": 0},
    "high": {"label": "Высокая", "color": "#F97316", "order": 1},
    "medium": {"label": "Средняя", "color": "#EAB308", "order": 2},
    "low": {"label": "Низкая", "color": "#22C55E", "order": 3},
}
DEFAULT_CATEGORIES = ("Работа", "Учёба", "Личное", "Встреча", "Другое")


def normalize_task(raw: Any) -> dict[str, Any] | None:
    """Convert legacy strings and fill metadata missing from older task objects."""
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
        priority = {"main": "high", "additional": "medium", "later": "low"}[focus]
        return {
            "id": uuid.uuid4().hex, "focus": focus, "text": text or raw.strip(),
            "duration_minutes": duration, "status": "todo", "priority": priority, "category": "Учёба",
        }
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
    status = str(raw.get("status", "todo"))
    if status not in STATUS_LEVELS:
        status = "todo"
    default_priority = {"main": "high", "additional": "medium", "later": "low"}[focus]
    priority = str(raw.get("priority", default_priority))
    if priority not in PRIORITY_LEVELS:
        priority = default_priority
    category = str(raw.get("category", "Другое")).strip() or "Другое"
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex),
        "focus": focus, "text": text, "duration_minutes": duration,
        "status": status, "priority": priority, "category": category,
    }


def normalize_tasks(raw_tasks: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_tasks, list):
        return []
    tasks = [task for item in raw_tasks if (task := normalize_task(item)) is not None]
    return sort_tasks(tasks)


def sort_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group by focus, preserving insertion order inside each focus group."""
    indexed = list(enumerate(tasks))
    indexed.sort(key=lambda pair: (FOCUS_LEVELS.get(pair[1].get("focus"), FOCUS_LEVELS["later"])["order"], pair[0]))
    return [task for _, task in indexed]


def planned_minutes(tasks: list[dict[str, Any]]) -> int:
    return sum(max(0, int(task.get("duration_minutes", 0))) for task in tasks)
