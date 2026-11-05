"""Schedule resolution for weekdays and date-specific overrides."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

DAY_KEYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAY_NAMES = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


def _day_data(config: dict[str, Any], current_date: date) -> dict[str, Any]:
    schedule = config.get("schedule", {})
    if not isinstance(schedule, dict):
        return {}
    special_dates = schedule.get("special_dates", {})
    special = special_dates.get(current_date.isoformat()) if isinstance(special_dates, dict) else None
    day_key = DAY_KEYS[current_date.weekday()]
    selected = special if isinstance(special, dict) else schedule.get(day_key, {})
    return selected if isinstance(selected, dict) else {}


def schedule_for_today(config: dict[str, Any], current_date: date | None = None) -> tuple[str, list[str]]:
    current_date = current_date or datetime.now().date()
    data = _day_data(config, current_date)
    tasks = data.get("tasks", [])
    if not isinstance(tasks, list):
        tasks = []
    cleaned = [str(task) for task in tasks if str(task).strip()]
    label = data.get("label")
    return (str(label) if label else DAY_NAMES[current_date.weekday()]), cleaned


def required_study_minutes_for_today(config: dict[str, Any], current_date: date | None = None) -> int:
    current_date = current_date or datetime.now().date()
    data = _day_data(config, current_date)
    rules = config.get("rules", {})
    if not isinstance(rules, dict):
        rules = {}
    value = data.get("required_study_minutes")
    if value is None:
        value = rules.get("required_study_minutes", rules.get("minimum_study_minutes_for_all_done", 90))
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 90
