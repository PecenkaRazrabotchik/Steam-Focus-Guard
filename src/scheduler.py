"""Resolve task lists for weekdays and date-specific overrides."""
from __future__ import annotations
from datetime import date, datetime
from typing import Any
from src.task_manager import normalize_tasks, planned_minutes

DAY_KEYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAY_NAMES = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")

def _day_data(config: dict[str, Any], current_date: date) -> dict[str, Any]:
    schedule = config.get("schedule", {})
    if not isinstance(schedule, dict):
        return {}
    special_dates = schedule.get("special_dates", {})
    special = special_dates.get(current_date.isoformat()) if isinstance(special_dates, dict) else None
    selected = special if isinstance(special, dict) else schedule.get(DAY_KEYS[current_date.weekday()], {})
    return selected if isinstance(selected, dict) else {}

def tasks_for_date(config: dict[str, Any], current_date: date | None = None) -> list[dict[str, Any]]:
    current_date = current_date or datetime.now().date()
    return normalize_tasks(_day_data(config, current_date).get("tasks", []))

def schedule_for_today(config: dict[str, Any], current_date: date | None = None) -> tuple[str, list[dict[str, Any]]]:
    current_date = current_date or datetime.now().date()
    data = _day_data(config, current_date)
    label = data.get("label")
    return (str(label) if label else DAY_NAMES[current_date.weekday()]), tasks_for_date(config, current_date)

def required_study_minutes_for_today(config: dict[str, Any], current_date: date | None = None) -> int:
    """New task model calculates the target from individual task durations."""
    current_date = current_date or datetime.now().date()
    data = _day_data(config, current_date)
    calculated = planned_minutes(normalize_tasks(data.get("tasks", [])))
    if calculated:
        return calculated
    try:
        return max(0, int(data.get("legacy_required_study_minutes", 0)))
    except (TypeError, ValueError):
        return 0
