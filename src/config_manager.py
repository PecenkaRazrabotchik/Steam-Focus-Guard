"""Default configuration and user configuration loading."""
from __future__ import annotations

import json
from typing import Any

from src.paths import CONFIG_PATH, DEFAULT_CONFIG_PATH, ensure_project_layout

DEFAULT_CONFIG: dict[str, Any] = {
    "app": {
        "steam_executable": "",
        "steam_process_names": ["steam.exe"],
        "scan_interval_ms": 250,
        "close_grace_seconds": 8,
        "launch_after_grant": True,
        "window_width": 650,
        "window_height": 700,
        "always_on_top": True,
    },
    "rules": {
        "required_study_minutes": 90
    },
    "ui": {
        "window_title": "Фокус: сначала дела, потом Steam",
        "heading": "Сначала важное — потом игры",
        "intro": "Сегодняшний план:",
        "date_line": "Сегодня: {date} · {weekday}",
        "empty_schedule": "На сегодня задания не заданы. Добавь их в config/config.json.",
        "study_button": "Сначала выполню задания",
        "settings_button": "Настройки",
        "reset_timer_button": "Сбросить таймер",
        "reset_timer_title": "Сбросить учебный таймер?",
        "reset_timer_message": "Прошедшее учебное время будет обнулено. Чтобы начать новую сессию, нажми «Сначала выполню задания». Продолжить?",
        "timer_not_started": "Учебное время: 00:00:00 / {required} · сессия не начата",
        "timer_study_display": "Учебное время: {elapsed} / {required} · осталось: {remaining}",
        "timer_game_display": "Игровой таймер: {remaining}",
        "check_button": "Проверить",
        "check_no_session_title": "Учебная сессия не начата",
        "check_no_session_message": "Сначала нажми «Сначала выполню задания». Норма на сегодня: {required}.",
        "check_remaining_title": "Нужно ещё позаниматься",
        "check_remaining_message": "Прошло: {elapsed}. До нормы {required} осталось: {remaining}.",
        "check_complete_title": "Учебная норма выполнена",
        "check_complete_message": "Засчитано учебного времени: {elapsed}. Дневная норма {required} выполнена. Полный доступ к Steam открыт.",
        "temporary_button": "Временно поиграть",
        "temporary_heading": "На сколько открыть Steam?",
        "unlimited_button": "Без ограничения",
        "thirty_minutes_button": "30 минут",
        "back_button": "Назад",
        "status_blocked": "Steam заблокирован до твоего решения.",
        "status_study": "Режим учёбы: сначала выполни план, затем возвращайся.",
        "status_timed": "Временный доступ активен. Осталось: {time_left}.",
        "status_unlimited": "Steam открыт до закрытия игры.",
        "study_started_title": "Учебная сессия отмечена",
        "study_started_message": "Отметил начало занятий. Когда закончишь, снова открой Steam и нажми «Проверить».",
        "time_warning_5": "Осталось 5 минут игры. Заверши текущий матч или сохранение.",
        "time_warning_1": "Осталась 1 минута. Steam скоро будет закрыт.",
        "time_finished_title": "Время вышло",
        "time_finished_message": "Лимит в 30 минут закончился. Steam закрыт.",
        "steam_not_found_title": "Не удалось найти Steam",
        "steam_not_found_message": "Разрешение выдано, но путь к steam.exe не найден. Укажи его в config/config.json или запусти Steam вручную.",
        "minimum_time_title": "Сначала нужно позаниматься",
        "minimum_time_message": "С момента начала учебной сессии прошло {elapsed} мин. Для полного доступа нужно не менее {required} мин.",
        "exit_title": "Остановить защиту?",
        "exit_message": "Защитник Steam будет закрыт. Пока он не запущен, попытки открыть Steam не будут перехватываться. Продолжить?",
        "already_running": "Защитник Steam уже запущен.",
        "startup_installed": "Автозапуск добавлен. Защитник будет запускаться при входе в Windows.",
        "startup_removed": "Автозапуск удалён.",
        "stop_requested": "Команда остановки отправлена защитнику.",
        "dependency_missing": "Не найден модуль psutil. Установи его командой: py -m pip install psutil",
        "config_error_title": "Ошибка config.json",
        "config_error_message": "Не удалось прочитать config.json. Используются встроенные настройки. Подробности: {error}",
        "notification_title": "Фокус",
        "close_button": "Закрыть окно",
        "footer_hint": "Расписание и надписи можно изменить в окне «Настройки».",
    },
    "schedule": {
        "monday": {
            "required_study_minutes": 90,
            "tasks": [
                "Главное: университетские задания — 45 минут",
                "Дополнительно, если есть силы: базы данных и SQL — 30 минут",
                "Минимум: английский — 10–15 минут"
            ]
        },
        "tuesday": {
            "required_study_minutes": 90,
            "tasks": [
                "Главное: Python — написать код или решить задачи, 45 минут",
                "Дополнительно: ААС или другое задание университета — 30 минут",
                "Минимум: повторить английские слова — 10–15 минут"
            ]
        },
        "wednesday": {
            "required_study_minutes": 90,
            "tasks": [
                "Главное: SQL — написать и проверить запросы, 45 минут",
                "Дополнительно: Python — повторить пройденное, 30 минут",
                "Минимум: английская грамматика или чтение — 10–15 минут"
            ]
        },
        "thursday": {
            "required_study_minutes": 90,
            "tasks": [
                "Главное: университетские задания и подготовка — 45 минут",
                "Дополнительно: Python — практика, 30 минут",
                "Минимум: английские слова — 10–15 минут"
            ]
        },
        "friday": {
            "required_study_minutes": 90,
            "tasks": [
                "Главное: закрыть срочные задания и проверить дедлайны — 45 минут",
                "Дополнительно: повторить SQL или Python по слабым местам — 30 минут",
                "Минимум: повторить английский за неделю — 10–15 минут"
            ]
        },
        "saturday": {
            "required_study_minutes": 60,
            "tasks": [
                "Гибкий день: выбрать одно самое важное или накопившееся задание — 45–60 минут",
                "По желанию: английский или повторение материала — 10–15 минут"
            ]
        },
        "sunday": {
            "required_study_minutes": 0,
            "tasks": [
                "Отдых и восстановление",
                "По желанию: составить план на следующую неделю — 10–15 минут"
            ]
        },
        "special_dates": {}
    }
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> tuple[dict[str, Any], str | None]:
    ensure_project_layout()
    if not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if DEFAULT_CONFIG_PATH.exists():
            CONFIG_PATH.write_text(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8-sig"), encoding="utf-8")
        else:
            CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        user_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        if not isinstance(user_config, dict):
            raise ValueError("Корневой элемент JSON должен быть объектом")
        return deep_merge(DEFAULT_CONFIG, user_config), None
    except Exception as exc:
        return deep_merge(DEFAULT_CONFIG, {}), str(exc)
