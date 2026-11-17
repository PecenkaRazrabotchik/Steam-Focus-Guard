"""Default configuration, legacy migration and persistence."""
from __future__ import annotations
import json
from typing import Any
from src.paths import CONFIG_PATH, DEFAULT_CONFIG_PATH, ensure_project_layout
from src.task_manager import normalize_tasks

DEFAULT_CONFIG: dict[str, Any] = {
    "app": {
        "steam_executable": "", "steam_process_names": ["steam.exe"],
        "scan_interval_ms": 400, "close_grace_seconds": 8, "launch_after_grant": True,
        "window_width": 1040, "window_height": 760,
        "always_on_top": False, "show_in_tray": True,
        "start_with_windows": False, "close_to_tray": True,
    },
    "rules": {"blocked_apps": [], "blocked_websites": [], "website_blocking_enabled": False},
    "ui": {
        "window_title": "Focus Guard", "heading": "План на сегодня",
        "intro": "Мои задачи",
        "empty_schedule": "Пока задач нет. Нажми «Добавить задачу», чтобы составить план.",
        "add_task_button": "Добавить задачу", "study_button": "Начать фокус",
        "pause_button": "Пауза", "resume_button": "Продолжить",
        "check_button": "Проверить задачи", "reset_timer_button": "Сбросить таймер",
        "settings_button": "Настройки",
        "status_message": "Выбери одну задачу и сосредоточься на ней.",
        "timer_not_started": "Фокус не запущен · план: {required}",
        "timer_study_display": "Фокус: {elapsed} / {required} · осталось {remaining}",
        "timer_paused_display": "Пауза · {elapsed} из {required}",
        "check_no_tasks_title": "Нет задач с длительностью",
        "check_no_tasks_message": "Добавь задачи и укажи для них время, чтобы проверить выполнение плана.",
        "check_no_session_title": "Фокус ещё не начат",
        "check_no_session_message": "Сначала нажми «Начать фокус». План на сегодня: {required}.",
        "check_remaining_title": "План ещё не завершён",
        "check_remaining_message": "Прошло {elapsed}. До запланированного времени осталось {remaining}.",
        "check_complete_title": "План выполнен",
        "check_complete_message": "Запланированное время достигнуто. Доступ к Steam открыт до закрытия игры.",
        "reset_timer_title": "Сбросить таймер?",
        "reset_timer_message": "Накопленное время текущей сессии будет обнулено.",
        "exit_title": "Закрыть Focus Guard?",
        "exit_message": "Защита будет остановлена. Продолжить?",
        "config_error_title": "Ошибка настроек",
        "config_error_message": "Не удалось прочитать конфигурацию: {error}",
        "footer_hint": "Задачи, ограничения и поведение приложения настраиваются здесь.",
    },
    "schedule": {
        "monday": {"tasks": []}, "tuesday": {"tasks": []}, "wednesday": {"tasks": []},
        "thursday": {"tasks": []}, "friday": {"tasks": []}, "saturday": {"tasks": []},
        "sunday": {"tasks": []}, "special_dates": {},
    },
}

def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result

def migrate_config(config: dict[str, Any]) -> dict[str, Any]:
    """Upgrade legacy text-only tasks without discarding user entries."""
    schedule = config.get("schedule")
    if isinstance(schedule, dict):
        for day_data in schedule.values():
            if isinstance(day_data, dict) and isinstance(day_data.get("tasks"), list):
                old_tasks = day_data["tasks"]
                was_legacy = any(isinstance(item, str) for item in old_tasks)
                day_data["tasks"] = normalize_tasks(old_tasks)
                if was_legacy and day_data.get("required_study_minutes") is not None:
                    day_data["legacy_required_study_minutes"] = day_data["required_study_minutes"]
                    day_data.pop("required_study_minutes", None)
    rules = config.setdefault("rules", {})
    if isinstance(rules, dict):
        rules.setdefault("blocked_apps", [])
        rules.setdefault("blocked_websites", [])
        rules.setdefault("website_blocking_enabled", False)
    app = config.setdefault("app", {})
    if isinstance(app, dict):
        app.setdefault("show_in_tray", True)
        app.setdefault("start_with_windows", False)
        app.setdefault("close_to_tray", True)
    return config

def load_config() -> tuple[dict[str, Any], str | None]:
    ensure_project_layout()
    if not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        source = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8-sig") if DEFAULT_CONFIG_PATH.exists() else json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2)
        CONFIG_PATH.write_text(source, encoding="utf-8")
    try:
        user_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        if not isinstance(user_config, dict):
            raise ValueError("Корневой элемент JSON должен быть объектом")
        migrated = migrate_config(user_config)
        merged = deep_merge(DEFAULT_CONFIG, migrated)
        if merged != user_config:
            save_config(merged)
        return merged, None
    except Exception as exc:
        return deep_merge(DEFAULT_CONFIG, {}), str(exc)

def save_config(config: dict[str, Any]) -> None:
    ensure_project_layout()
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_PATH.with_suffix(".json.tmp")
    temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(CONFIG_PATH)
