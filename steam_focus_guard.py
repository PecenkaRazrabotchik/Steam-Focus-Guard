from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import psutil
except ImportError:
    psutil = None


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
STATE_PATH = BASE_DIR / "state.json"
LOG_PATH = BASE_DIR / "activity_log.csv"
STOP_REQUEST_PATH = BASE_DIR / "stop.request"

DAY_KEYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
DAY_NAMES = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)

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
        "minimum_study_minutes_for_all_done": 0
    },
    "ui": {
        "window_title": "Фокус: сначала дела, потом Steam",
        "heading": "Сначала важное — потом игры",
        "intro": "Сегодняшний план:",
        "date_line": "Сегодня: {date} · {weekday}",
        "empty_schedule": "На сегодня задания не заданы. Добавь их в config.json.",
        "study_button": "Сначала выполню задания",
        "temporary_button": "Временно поиграть",
        "all_done_button": "Всё сделано — открыть Steam",
        "temporary_heading": "На сколько открыть Steam?",
        "unlimited_button": "Без ограничения",
        "thirty_minutes_button": "30 минут",
        "back_button": "Назад",
        "status_blocked": "Steam заблокирован до твоего решения.",
        "status_study": "Режим учёбы: сначала выполни план, затем возвращайся.",
        "status_timed": "Временный доступ активен. Осталось: {time_left}.",
        "status_unlimited": "Steam открыт до закрытия игры.",
        "study_started_title": "Учебная сессия отмечена",
        "study_started_message": "Отметил начало занятий. Когда закончишь, снова открой Steam и выбери «Всё сделано».",
        "time_warning_5": "Осталось 5 минут игры. Заверши текущий матч или сохранение.",
        "time_warning_1": "Осталась 1 минута. Steam скоро будет закрыт.",
        "time_finished_title": "Время вышло",
        "time_finished_message": "Лимит в 30 минут закончился. Steam закрыт.",
        "steam_not_found_title": "Не удалось найти Steam",
        "steam_not_found_message": "Разрешение выдано, но путь к steam.exe не найден. Укажи его в config.json или запусти Steam вручную.",
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
        "footer_hint": "План и все надписи можно изменить в config.json.",
    },
    "schedule": {
        "monday": {
            "tasks": [
                "Главное: университетские задания — 45 минут",
                "Дополнительно, если есть силы: базы данных и SQL — 30 минут",
                "Минимум: английский — 10–15 минут"
            ]
        },
        "tuesday": {
            "tasks": [
                "Главное: Python — написать код или решить задачи, 45 минут",
                "Дополнительно: ААС или другое задание университета — 30 минут",
                "Минимум: повторить английские слова — 10–15 минут"
            ]
        },
        "wednesday": {
            "tasks": [
                "Главное: SQL — написать и проверить запросы, 45 минут",
                "Дополнительно: Python — повторить пройденное, 30 минут",
                "Минимум: английская грамматика или чтение — 10–15 минут"
            ]
        },
        "thursday": {
            "tasks": [
                "Главное: университетские задания и подготовка — 45 минут",
                "Дополнительно: Python — практика, 30 минут",
                "Минимум: английские слова — 10–15 минут"
            ]
        },
        "friday": {
            "tasks": [
                "Главное: закрыть срочные задания и проверить дедлайны — 45 минут",
                "Дополнительно: повторить SQL или Python по слабым местам — 30 минут",
                "Минимум: повторить английский за неделю — 10–15 минут"
            ]
        },
        "saturday": {
            "tasks": [
                "Гибкий день: выбрать одно самое важное или накопившееся задание — 45–60 минут",
                "По желанию: английский или повторение материала — 10–15 минут"
            ]
        },
        "sunday": {
            "tasks": [
                "Отдых и восстановление",
                "По желанию: составить план на следующую неделю — 10–15 минут"
            ]
        },
        "special_dates": {}
    }
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge user settings over defaults while preserving missing default keys."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> tuple[dict[str, Any], str | None]:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
        return DEFAULT_CONFIG, None
    try:
        user_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        if not isinstance(user_config, dict):
            raise ValueError("Корневой элемент JSON должен быть объектом")
        return deep_merge(DEFAULT_CONFIG, user_config), None
    except Exception as exc:  # Keep the guard available even if config was edited incorrectly.
        return DEFAULT_CONFIG, str(exc)


def save_json(path: Path, data: dict[str, Any]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def log_event(event: str, details: str = "") -> None:
    new_file = not LOG_PATH.exists()
    with LOG_PATH.open("a", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file, delimiter=";")
        if new_file:
            writer.writerow(["Время", "Событие", "Подробности"])
        writer.writerow([datetime.now().astimezone().isoformat(timespec="seconds"), event, details])


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


class SteamFocusGuard:
    def __init__(self, background: bool = False) -> None:
        import tkinter as tk
        from tkinter import messagebox

        self.tk = tk
        self.messagebox = messagebox
        self.config, self.config_error = load_config()
        self.ui_text: dict[str, str] = self.config["ui"]
        self.app_config: dict[str, Any] = self.config["app"]
        self.running = True
        self.background = background
        self.detected_steam_path: str | None = None
        self.notification_window = None
        self.gate_visible = True
        self.temp_view_visible = False
        self._gate_was_requested = False
        self._steam_seen_in_session = False
        self._steam_missing_since: float | None = None
        self._permission_granted_at = 0.0
        self._last_process_scan: list[Any] = []
        self._timer_end: float | None = None
        self._warned_5 = False
        self._warned_1 = False

        self.state = self._load_state()
        self.mode = self.state.get("mode", "blocked")
        if self.mode == "unlimited":
            # Unlimited permission is deliberately session-only and is not restored after a guard restart.
            self.mode = "blocked"
        self.study_started_at = self.state.get("study_started_at")
        if self.mode == "timed":
            self._timer_end = self.state.get("timed_until")
            if not isinstance(self._timer_end, (int, float)) or self._timer_end <= time.time():
                self.mode = "blocked"
                self._timer_end = None
        self._save_state()

        self.root = tk.Tk()
        self.root.title(self.ui_text["window_title"])
        width = int(self.app_config.get("window_width", 650))
        height = int(self.app_config.get("window_height", 700))
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(540, 560)
        self.root.configure(bg="#151820")
        if self.app_config.get("always_on_top", True):
            self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self.request_exit)

        self._build_ui()
        self._refresh_ui()
        if self.config_error:
            self.root.after(400, lambda: self.messagebox.showwarning(
                self.ui_text["config_error_title"],
                self.ui_text["config_error_message"].format(error=self.config_error),
                parent=self.root,
            ))
        if self.background:
            self.root.after(1400, self._minimize_startup_window)
        self._schedule_monitor()

    def _load_state(self) -> dict[str, Any]:
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_state(self) -> None:
        save_json(STATE_PATH, {
            "mode": self.mode,
            "study_started_at": self.study_started_at,
            "timed_until": self._timer_end,
        })

    def t(self, key: str, **kwargs: Any) -> str:
        value = str(self.ui_text.get(key, key))
        try:
            return value.format(**kwargs)
        except (KeyError, ValueError):
            return value

    def _minimize_startup_window(self) -> None:
        if self.running and not self._gate_was_requested:
            self.root.iconify()

    def _build_ui(self) -> None:
        tk = self.tk
        self.outer = tk.Frame(self.root, bg="#151820", padx=28, pady=24)
        self.outer.pack(fill="both", expand=True)

        self.heading_label = tk.Label(
            self.outer, text="", bg="#151820", fg="#f2f4f8",
            font=("Segoe UI", 19, "bold"), wraplength=580, justify="left"
        )
        self.heading_label.pack(anchor="w", pady=(0, 8))

        self.date_label = tk.Label(
            self.outer, text="", bg="#151820", fg="#a9b2c2",
            font=("Segoe UI", 10)
        )
        self.date_label.pack(anchor="w", pady=(0, 18))

        self.status_label = tk.Label(
            self.outer, text="", bg="#222936", fg="#d9e2f2",
            font=("Segoe UI", 10), padx=12, pady=10, wraplength=560, justify="left"
        )
        self.status_label.pack(fill="x", pady=(0, 18))

        self.plan_heading = tk.Label(
            self.outer, text="", bg="#151820", fg="#f2f4f8",
            font=("Segoe UI", 12, "bold")
        )
        self.plan_heading.pack(anchor="w", pady=(0, 8))

        self.plan_box = tk.Text(
            self.outer, height=11, wrap="word", bg="#202632", fg="#e0e6ef",
            insertbackground="#e0e6ef", relief="flat", borderwidth=0,
            font=("Segoe UI", 11), padx=14, pady=12, spacing1=3, spacing3=7
        )
        self.plan_box.pack(fill="both", expand=True)
        self.plan_box.configure(state="disabled")

        self.action_frame = tk.Frame(self.outer, bg="#151820")
        self.action_frame.pack(fill="x", pady=(20, 0))

        self.primary_button = self._make_button(self.action_frame, "study_button", self.mark_study_started, primary=True)
        self.primary_button.pack(fill="x", pady=4)
        self.temporary_button = self._make_button(self.action_frame, "temporary_button", self.show_temporary_options)
        self.temporary_button.pack(fill="x", pady=4)
        self.done_button = self._make_button(self.action_frame, "all_done_button", self.grant_all_done)
        self.done_button.pack(fill="x", pady=4)

        self.temp_frame = tk.Frame(self.outer, bg="#151820")
        self.temp_heading = tk.Label(
            self.temp_frame, text="", bg="#151820", fg="#f2f4f8",
            font=("Segoe UI", 13, "bold")
        )
        self.temp_heading.pack(anchor="w", pady=(0, 12))
        self.temp_unlimited_button = self._make_button(self.temp_frame, "unlimited_button", self.grant_temporary_unlimited, primary=True)
        self.temp_unlimited_button.pack(fill="x", pady=4)
        self.temp_30_button = self._make_button(self.temp_frame, "thirty_minutes_button", self.grant_30_minutes)
        self.temp_30_button.pack(fill="x", pady=4)
        self.back_button = self._make_button(self.temp_frame, "back_button", self.show_main_options)
        self.back_button.pack(fill="x", pady=(12, 4))

        self.footer_label = tk.Label(
            self.outer, text=self.t("footer_hint"), bg="#151820", fg="#788397",
            font=("Segoe UI", 9), wraplength=570, justify="left"
        )
        self.footer_label.pack(anchor="w", pady=(16, 0))

    def _make_button(self, parent: Any, key: str, command: Any, primary: bool = False) -> Any:
        tk = self.tk
        bg = "#365d9b" if primary else "#2b3443"
        active = "#426fb4" if primary else "#39465a"
        button = tk.Button(
            parent, text=self.t(key), command=command,
            bg=bg, fg="#ffffff", activebackground=active, activeforeground="#ffffff",
            relief="flat", borderwidth=0, cursor="hand2", anchor="center",
            font=("Segoe UI", 11, "bold" if primary else "normal"), padx=12, pady=11
        )
        return button

    def _schedule_for_today(self) -> tuple[str, list[str]]:
        now = datetime.now()
        date_key = now.date().isoformat()
        schedule = self.config.get("schedule", {})
        special = schedule.get("special_dates", {}).get(date_key)
        day_key = DAY_KEYS[now.weekday()]
        day_data = special if isinstance(special, dict) else schedule.get(day_key, {})
        if not isinstance(day_data, dict):
            day_data = {}
        tasks = day_data.get("tasks", [])
        if not isinstance(tasks, list):
            tasks = []
        tasks = [str(task) for task in tasks if str(task).strip()]
        custom_label = day_data.get("label")
        day_name = str(custom_label) if custom_label else DAY_NAMES[now.weekday()]
        return day_name, tasks

    def _refresh_ui(self, extra_status: str | None = None) -> None:
        day_name, tasks = self._schedule_for_today()
        now = datetime.now()
        self.heading_label.configure(text=self.t("heading"))
        self.date_label.configure(text=self.t("date_line", date=now.strftime("%d.%m.%Y"), weekday=day_name))
        self.plan_heading.configure(text=self.t("intro"))
        self.plan_box.configure(state="normal")
        self.plan_box.delete("1.0", "end")
        if tasks:
            for index, task in enumerate(tasks, start=1):
                self.plan_box.insert("end", f"{index}. {task}\n\n")
        else:
            self.plan_box.insert("end", self.t("empty_schedule"))
        self.plan_box.configure(state="disabled")

        if extra_status:
            status = extra_status
        elif self.mode == "timed" and self._timer_end:
            remaining = max(0, int(self._timer_end - time.time()))
            status = self.t("status_timed", time_left=self._format_seconds(remaining))
        elif self.mode == "unlimited":
            status = self.t("status_unlimited")
        elif self.mode == "study":
            status = self.t("status_study")
        else:
            status = self.t("status_blocked")
        self.status_label.configure(text=status)
        self.footer_label.configure(text=self.t("footer_hint"))

    @staticmethod
    def _format_seconds(seconds: int) -> str:
        minutes, secs = divmod(max(0, seconds), 60)
        return f"{minutes:02d}:{secs:02d}"

    def show_temporary_options(self) -> None:
        self.action_frame.pack_forget()
        self.plan_heading.pack_forget()
        self.plan_box.pack_forget()
        self.temp_frame.pack(fill="x", pady=(28, 0))
        self.temp_heading.configure(text=self.t("temporary_heading"))
        self.temp_view_visible = True
        self.root.deiconify()
        self.root.lift()

    def show_main_options(self) -> None:
        self.temp_frame.pack_forget()
        self.plan_heading.pack(before=self.footer_label, anchor="w", pady=(0, 8))
        self.plan_box.pack(before=self.footer_label, fill="both", expand=True)
        self.action_frame.pack(before=self.footer_label, fill="x", pady=(20, 0))
        self.temp_view_visible = False
        self._refresh_ui()

    def _bring_to_front(self) -> None:
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except Exception:
            pass

    def show_gate(self, extra_status: str | None = None) -> None:
        self._gate_was_requested = True
        self.show_main_options()
        self._refresh_ui(extra_status)
        self.gate_visible = True
        self._bring_to_front()

    def mark_study_started(self) -> None:
        started_today = False
        if self.study_started_at:
            try:
                started_today = datetime.fromtimestamp(float(self.study_started_at)).date() == datetime.now().date()
            except (TypeError, ValueError, OSError):
                started_today = False
        if not started_today:
            self.study_started_at = time.time()
        self.mode = "study"
        self._save_state()
        log_event("study_started", "Пользователь отметил начало занятий")
        self._refresh_ui(self.t("study_started_message"))
        self.root.iconify()

    def _check_minimum_study_time(self) -> bool:
        required = max(0, int(self.config.get("rules", {}).get("minimum_study_minutes_for_all_done", 0)))
        if required <= 0:
            return True
        started_today = False
        if self.study_started_at:
            try:
                started_today = datetime.fromtimestamp(float(self.study_started_at)).date() == datetime.now().date()
            except (TypeError, ValueError, OSError):
                started_today = False
        if not started_today:
            elapsed = 0
        else:
            elapsed = max(0, int((time.time() - float(self.study_started_at)) / 60))
        if elapsed >= required:
            return True
        self.messagebox.showwarning(
            self.t("minimum_time_title"),
            self.t("minimum_time_message", elapsed=elapsed, required=required),
            parent=self.root,
        )
        return False

    def grant_all_done(self) -> None:
        if not self._check_minimum_study_time():
            return
        log_event("all_done_unlimited", "Пользователь отметил выполнение плана")
        self._grant_unlimited()

    def grant_temporary_unlimited(self) -> None:
        log_event("temporary_unlimited", "Выдан неограниченный временный доступ")
        self._grant_unlimited()

    def _grant_unlimited(self) -> None:
        self.mode = "unlimited"
        self._timer_end = None
        self._permission_granted_at = time.monotonic()
        self._steam_seen_in_session = False
        self._steam_missing_since = None
        self._save_state()
        self._launch_steam_or_notify()
        self.root.iconify()

    def grant_30_minutes(self) -> None:
        self.mode = "timed"
        self._timer_end = time.time() + 30 * 60
        self._warned_5 = False
        self._warned_1 = False
        self._permission_granted_at = time.monotonic()
        self._steam_seen_in_session = False
        self._steam_missing_since = None
        self._save_state()
        log_event("temporary_30m_started", "Выдан доступ на 30 минут")
        self._launch_steam_or_notify()
        self.root.iconify()

    def _launch_steam_or_notify(self) -> None:
        if not self.app_config.get("launch_after_grant", True):
            return
        executable = get_steam_executable(self.config, self.detected_steam_path)
        if executable is None:
            self.show_notification(self.t("steam_not_found_message"), duration_ms=9000)
            return
        try:
            flags = 0
            if os.name == "nt":
                flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
            subprocess.Popen([str(executable)], cwd=str(executable.parent), creationflags=flags)
            self.detected_steam_path = str(executable)
        except Exception as exc:
            self.show_notification(f"{self.t('steam_not_found_message')}\n{exc}", duration_ms=10000)

    def show_notification(self, message: str, duration_ms: int = 6500) -> None:
        tk = self.tk
        if self.notification_window is not None:
            try:
                self.notification_window.destroy()
            except Exception:
                pass
        window = tk.Toplevel(self.root)
        self.notification_window = window
        window.title(self.t("notification_title"))
        window.configure(bg="#222936")
        window.resizable(False, False)
        window.attributes("-topmost", True)
        label = tk.Label(
            window, text=message, bg="#222936", fg="#ffffff",
            font=("Segoe UI", 11), padx=18, pady=16,
            wraplength=420, justify="left"
        )
        label.pack(fill="both", expand=True)
        window.update_idletasks()
        x = max(0, self.root.winfo_screenwidth() - window.winfo_width() - 40)
        y = max(0, self.root.winfo_screenheight() - window.winfo_height() - 80)
        window.geometry(f"+{x}+{y}")
        window.after(duration_ms, lambda: self._close_notification(window))
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass

    def _close_notification(self, window: Any) -> None:
        try:
            window.destroy()
        except Exception:
            pass
        if self.notification_window is window:
            self.notification_window = None

    def _find_steam_processes(self) -> list[Any]:
        if psutil is None:
            return []
        names = {str(name).lower() for name in self.app_config.get("steam_process_names", ["steam.exe"])}
        found = []
        for process in psutil.process_iter(attrs=["pid", "name", "exe"]):
            try:
                name = (process.info.get("name") or "").lower()
                if name in names:
                    found.append(process)
                    exe = process.info.get("exe")
                    if exe:
                        self.detected_steam_path = exe
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return found

    def _terminate_steam_processes(self, processes: list[Any]) -> None:
        if psutil is None:
            return
        to_stop: dict[int, Any] = {}
        for process in processes:
            try:
                for child in process.children(recursive=True):
                    to_stop[child.pid] = child
                to_stop[process.pid] = process
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        targets = list(to_stop.values())
        for process in targets:
            try:
                process.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        _, alive = psutil.wait_procs(targets, timeout=0.8)
        for process in alive:
            try:
                process.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    def _expire_timer(self) -> None:
        processes = self._find_steam_processes()
        if processes:
            self._terminate_steam_processes(processes)
        self.mode = "blocked"
        self._timer_end = None
        self.study_started_at = None
        self._save_state()
        log_event("time_expired", "Лимит 30 минут истёк; Steam закрыт")
        self.show_gate(self.t("time_finished_message"))
        self.show_notification(self.t("time_finished_message"), duration_ms=8000)

    def _check_timer(self) -> None:
        if self.mode != "timed" or self._timer_end is None:
            return
        remaining = int(self._timer_end - time.time())
        elapsed = 1800 - remaining
        if remaining <= 0:
            self._expire_timer()
            return
        if 1500 <= elapsed < 1740 and not self._warned_5:
            self._warned_5 = True
            log_event("warning_5m", "Осталось 5 минут")
            self.show_notification(self.t("time_warning_5"))
        if elapsed >= 1740 and not self._warned_1:
            self._warned_1 = True
            log_event("warning_1m", "Осталась 1 минута")
            self.show_notification(self.t("time_warning_1"))
        remaining_text = self.t("status_timed", time_left=self._format_seconds(remaining))
        self.status_label.configure(text=remaining_text)

    def _monitor_processes(self) -> None:
        if not self.running:
            return
        if STOP_REQUEST_PATH.exists():
            try:
                STOP_REQUEST_PATH.unlink()
            except OSError:
                pass
            self._shutdown()
            return

        self._check_timer()
        processes = self._find_steam_processes()
        is_running = bool(processes)

        if self.mode in ("blocked", "study"):
            if is_running:
                for process in processes:
                    try:
                        log_event("steam_blocked", f"Попытка запуска: PID {process.pid}")
                    except Exception:
                        pass
                self._terminate_steam_processes(processes)
                if not self.gate_visible or self.root.state() == "iconic":
                    self.show_gate()
                elif self.root.state() == "withdrawn":
                    self.show_gate()
        elif self.mode == "timed":
            if is_running:
                self._steam_seen_in_session = True
                self._steam_missing_since = None
        elif self.mode == "unlimited":
            if is_running:
                self._steam_seen_in_session = True
                self._steam_missing_since = None
            elif self._steam_seen_in_session:
                if self._steam_missing_since is None:
                    self._steam_missing_since = time.monotonic()
                elif time.monotonic() - self._steam_missing_since >= float(self.app_config.get("close_grace_seconds", 8)):
                    self.mode = "blocked"
                    self._timer_end = None
                    self.study_started_at = None
                    self._steam_seen_in_session = False
                    self._steam_missing_since = None
                    self._save_state()
                    log_event("steam_session_closed", "Steam закрыт; неограниченный доступ отозван")
                    self._refresh_ui()

        interval = max(100, int(self.app_config.get("scan_interval_ms", 250)))
        self.root.after(interval, self._monitor_processes)

    def _schedule_monitor(self) -> None:
        self.root.after(300, self._monitor_processes)

    def request_exit(self) -> None:
        answer = self.messagebox.askyesno(
            self.t("exit_title"), self.t("exit_message"), parent=self.root
        )
        if answer:
            self._shutdown()

    def _shutdown(self) -> None:
        self.running = False
        log_event("guard_stopped", "Защитник остановлен")
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self) -> None:
        self.root.mainloop()


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
    command = f'"{python_path}" "{Path(__file__).resolve()}" --background'
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


def main() -> int:
    args = set(sys.argv[1:])
    if "--install-startup" in args:
        return install_startup()
    if "--uninstall-startup" in args:
        return uninstall_startup()
    if "--stop" in args:
        STOP_REQUEST_PATH.write_text("stop", encoding="utf-8")
        config, _ = load_config()
        print(config["ui"]["stop_requested"])
        return 0

    if os.name != "nt":
        print("Этот скрипт рассчитан на Windows.")
        return 1
    if psutil is None:
        config, _ = load_config()
        print(config["ui"]["dependency_missing"])
        return 1

    # A simple lock prevents accidentally running two watchdog instances.
    try:
        import msvcrt
        lock_file = (BASE_DIR / "guard.lock").open("a+")
        lock_file.seek(0)
        if lock_file.read(1) == "":
            lock_file.write("0")
            lock_file.flush()
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        config, _ = load_config()
        print(config["ui"]["already_running"])
        return 0
    except Exception:
        lock_file = None

    try:
        if STOP_REQUEST_PATH.exists():
            STOP_REQUEST_PATH.unlink()
    except OSError:
        pass

    try:
        app = SteamFocusGuard(background="--background" in args)
        app.run()
    finally:
        try:
            if lock_file:
                import msvcrt
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                lock_file.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
