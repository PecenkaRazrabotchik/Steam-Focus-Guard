"""Main Focus Guard desktop application."""
from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

try:
    import psutil
except ImportError:
    psutil = None

from tkinter import messagebox

from src.config_manager import load_config, save_config
from src.paths import STATE_PATH, STOP_REQUEST_PATH
from src.scheduler import DAY_KEYS, DAY_NAMES, required_study_minutes_for_today, schedule_for_today
from src.steam_utils import get_steam_executable
from src.storage import log_event, save_json
from src.task_manager import FOCUS_LEVELS, normalize_tasks, sort_tasks
from src.tray import SystemTrayController
from src.website_blocker import request_admin_sync


class SteamFocusGuard:
    """Owns the GUI, focus timer and enforcement loop."""

    BG = "#111827"
    PANEL = "#1F2937"
    PANEL_LIGHT = "#263244"
    TEXT = "#F9FAFB"
    MUTED = "#9CA3AF"
    BLUE = "#3B82F6"
    RED = "#DC5555"

    def __init__(self, background: bool = False) -> None:
        import customtkinter as ctk
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.ctk = ctk
        self.messagebox = messagebox
        self.config, self.config_error = load_config()
        self.ui_text = self.config["ui"]
        self.app_config = self.config["app"]
        self.running = True
        self.background = background
        self.detected_steam_path: str | None = None
        self.selected_date = datetime.now().date()
        self.mode = "blocked"
        self._steam_seen = False
        self._steam_missing_since: float | None = None
        self._last_scan = 0.0
        self._settings_window = None
        self._tray: SystemTrayController | None = None
        self._load_state()

        self.root = ctk.CTk()
        self.root.title(self.ui_text["window_title"])
        self.root.geometry(f'{int(self.app_config.get("window_width", 1040))}x{int(self.app_config.get("window_height", 760))}')
        self.root.minsize(780, 620)
        self.root.configure(fg_color=self.BG)
        self.root.attributes("-topmost", bool(self.app_config.get("always_on_top", False)))
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._build_ui()
        self._refresh_ui()
        self._update_timer_display()
        self._sync_tray()
        if self.config_error:
            self.root.after(500, lambda: messagebox.showwarning(
                self.ui_text["config_error_title"],
                self.ui_text["config_error_message"].format(error=self.config_error),
                parent=self.root,
            ))
        if self.background:
            self.root.after(1000, self._hide_to_tray_or_minimise)
        self.root.after(300, self._monitor_processes)

    def _load_state(self) -> None:
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                state = {}
        except (OSError, json.JSONDecodeError):
            state = {}
        self.study_date = state.get("study_date")
        self.study_elapsed_seconds = max(0, int(state.get("study_elapsed_seconds", 0) or 0))
        self.study_running_since = state.get("study_running_since")
        legacy_start = state.get("study_started_at")
        today = datetime.now().date().isoformat()
        if not self.study_date and legacy_start:
            try:
                timestamp = float(legacy_start)
                if datetime.fromtimestamp(timestamp).date().isoformat() == today:
                    self.study_date = today
                    self.study_running_since = timestamp
            except (TypeError, ValueError, OSError, OverflowError):
                pass
        if self.study_date != today:
            self.study_date = None
            self.study_elapsed_seconds = 0
            self.study_running_since = None
        # An unlimited Steam permission must never survive an application restart.
        if state.get("mode") == "unlimited":
            self.mode = "blocked"

    def _save_state(self) -> None:
        save_json(STATE_PATH, {
            "mode": self.mode,
            "study_date": self.study_date,
            "study_elapsed_seconds": self.study_elapsed_seconds,
            "study_running_since": self.study_running_since,
        })

    def t(self, key: str, **kwargs: Any) -> str:
        value = str(self.ui_text.get(key, key))
        try:
            return value.format(**kwargs)
        except (KeyError, ValueError):
            return value

    def _build_ui(self) -> None:
        ctk = self.ctk
        shell = ctk.CTkFrame(self.root, fg_color="transparent")
        shell.pack(fill="both", expand=True, padx=26, pady=22)

        header = ctk.CTkFrame(shell, fg_color="transparent")
        header.pack(fill="x", pady=(0, 16))
        heading = ctk.CTkFrame(header, fg_color="transparent")
        heading.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(heading, text="FOCUS GUARD", text_color=self.BLUE, font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(heading, text=self.t("heading"), text_color=self.TEXT, font=ctk.CTkFont(size=27, weight="bold")).pack(anchor="w", pady=(2, 2))
        date_row = ctk.CTkFrame(heading, fg_color="transparent")
        date_row.pack(anchor="w", pady=(2, 0))
        self.previous_day_button = ctk.CTkButton(date_row, text="‹", width=28, height=26, corner_radius=8, fg_color=self.PANEL_LIGHT, hover_color="#374151", command=lambda: self.change_selected_day(-1))
        self.previous_day_button.pack(side="left", padx=(0, 6))
        self.date_label = ctk.CTkLabel(date_row, text="", text_color=self.MUTED)
        self.date_label.pack(side="left")
        self.next_day_button = ctk.CTkButton(date_row, text="›", width=28, height=26, corner_radius=8, fg_color=self.PANEL_LIGHT, hover_color="#374151", command=lambda: self.change_selected_day(1))
        self.next_day_button.pack(side="left", padx=(6, 0))
        self.settings_button = ctk.CTkButton(header, text="⚙  Настройки", width=142, height=40, corner_radius=12, fg_color=self.PANEL_LIGHT, hover_color="#334155", command=self.open_settings)
        self.settings_button.pack(side="right", padx=(12, 0), pady=(16, 0))

        timer_card = ctk.CTkFrame(shell, fg_color=self.PANEL, corner_radius=18)
        timer_card.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(timer_card, text="ВРЕМЯ ФОКУСА", text_color=self.MUTED, font=ctk.CTkFont(size=10, weight="bold")).pack(anchor="w", padx=20, pady=(14, 2))
        self.timer_label = ctk.CTkLabel(timer_card, text="", text_color=self.TEXT, font=ctk.CTkFont(size=23, weight="bold"))
        self.timer_label.pack(anchor="w", padx=20, pady=(0, 12))
        self.status_label = ctk.CTkLabel(timer_card, text=self.t("status_message"), text_color="#C4CDD9", font=ctk.CTkFont(size=12), anchor="w", justify="left", wraplength=880)
        self.status_label.pack(fill="x", padx=20, pady=(0, 15))

        task_header = ctk.CTkFrame(shell, fg_color="transparent")
        task_header.pack(fill="x", pady=(10, 10))
        ctk.CTkLabel(task_header, text=self.t("intro"), text_color=self.TEXT, font=ctk.CTkFont(size=18, weight="bold")).pack(side="left")
        self.add_task_button = ctk.CTkButton(task_header, text="+  Добавить задачу", width=155, height=38, corner_radius=11, command=self.open_task_dialog)
        self.add_task_button.pack(side="right")

        self.task_list_frame = ctk.CTkScrollableFrame(shell, fg_color="transparent", corner_radius=14)
        self.task_list_frame.pack(fill="both", expand=True)

        actions = ctk.CTkFrame(shell, fg_color="transparent")
        actions.pack(fill="x", pady=(16, 0))
        self.start_button = ctk.CTkButton(actions, text=self.t("study_button"), height=44, corner_radius=12, fg_color=self.BLUE, hover_color="#2563EB", command=self.mark_study_started)
        self.start_button.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.pause_button = ctk.CTkButton(actions, text=self.t("pause_button"), height=44, width=112, corner_radius=12, fg_color=self.PANEL_LIGHT, hover_color="#374151", command=self.toggle_study_pause)
        self.pause_button.pack(side="left", padx=4)
        self.check_button = ctk.CTkButton(actions, text=self.t("check_button"), height=44, width=155, corner_radius=12, fg_color="#166534", hover_color="#15803D", command=self.check_study_time)
        self.check_button.pack(side="left", padx=4)
        self.reset_timer_button = ctk.CTkButton(actions, text=self.t("reset_timer_button"), height=44, width=145, corner_radius=12, fg_color=self.PANEL_LIGHT, hover_color="#374151", command=self.reset_study_timer)
        self.reset_timer_button.pack(side="left", padx=(8, 0))

        ctk.CTkLabel(shell, text=self.t("footer_hint"), text_color="#6B7280", font=ctk.CTkFont(size=10)).pack(anchor="w", pady=(12, 0))

    def _slot_for_date(self, selected_date) -> dict[str, Any]:
        schedule = self.config.setdefault("schedule", {})
        special_dates = schedule.setdefault("special_dates", {})
        date_key = selected_date.isoformat()
        if date_key in special_dates and isinstance(special_dates[date_key], dict):
            return special_dates[date_key]
        return schedule.setdefault(DAY_KEYS[selected_date.weekday()], {"tasks": []})

    def _today_slot(self) -> dict[str, Any]:
        return self._slot_for_date(datetime.now().date())

    def _selected_tasks(self) -> list[dict[str, Any]]:
        return normalize_tasks(self._slot_for_date(self.selected_date).get("tasks", []))

    def _today_tasks(self) -> list[dict[str, Any]]:
        return normalize_tasks(self._today_slot().get("tasks", []))

    def _write_selected_tasks(self, tasks: list[dict[str, Any]]) -> None:
        self._slot_for_date(self.selected_date)["tasks"] = sort_tasks(tasks)
        save_config(self.config)
        self._refresh_ui()
        self._update_timer_display(schedule_next=False)

    def change_selected_day(self, delta: int) -> None:
        self.selected_date += timedelta(days=delta)
        self._refresh_ui()
        self._update_timer_display(schedule_next=False)

    def _task_dialog(self, task: dict[str, Any] | None = None) -> None:
        ctk = self.ctk
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Новая задача" if task is None else "Изменить задачу")
        dialog.geometry("640x430")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        selected = {"focus": (task or {}).get("focus", "main")}
        ctk.CTkLabel(dialog, text="На чём будет фокус?", font=ctk.CTkFont(size=21, weight="bold")).pack(anchor="w", padx=24, pady=(22, 6))
        ctk.CTkLabel(dialog, text="Приоритет определяет порядок задач в общем списке.", text_color=self.MUTED).pack(anchor="w", padx=24, pady=(0, 14))
        choices = ctk.CTkFrame(dialog, fg_color="transparent")
        choices.pack(fill="x", padx=20)
        form = ctk.CTkFrame(dialog, fg_color=self.PANEL, corner_radius=14)
        form.pack(fill="x", padx=24, pady=22)
        badge = ctk.CTkLabel(form, text="", width=150, height=38, corner_radius=10, text_color="#111827", font=ctk.CTkFont(weight="bold"))
        badge.pack(side="left", padx=14, pady=18)
        entry = ctk.CTkEntry(form, height=42, placeholder_text="Название или описание задачи", corner_radius=10)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 14), pady=18)
        entry.insert(0, (task or {}).get("text", ""))
        def select_focus(level: str) -> None:
            selected["focus"] = level
            meta = FOCUS_LEVELS[level]
            badge.configure(text=meta["label"], fg_color=meta["color"])
            for key, button in focus_buttons.items():
                button.configure(border_width=2 if key == level else 0, border_color=meta["color"] if key == level else self.PANEL_LIGHT)
        focus_buttons = {}
        for level in ("main", "additional", "later"):
            meta = FOCUS_LEVELS[level]
            button = ctk.CTkButton(choices, text=meta["label"], fg_color=meta["color"], text_color="#111827", hover_color=meta["color"], height=38, corner_radius=10, command=lambda value=level: select_focus(value))
            button.pack(side="left", fill="x", expand=True, padx=4)
            focus_buttons[level] = button

        select_focus(selected["focus"])

        timing = ctk.CTkFrame(dialog, fg_color="transparent")
        timing.pack(fill="x", padx=24)
        ctk.CTkLabel(timing, text="Время на задачу", font=ctk.CTkFont(weight="bold")).pack(side="left")
        hour = ctk.CTkEntry(timing, width=76, height=38, placeholder_text="ч")
        hour.pack(side="right", padx=(8, 0))
        minute = ctk.CTkEntry(timing, width=76, height=38, placeholder_text="мин")
        minute.pack(side="right", padx=(8, 0))
        duration = int((task or {}).get("duration_minutes", 0))
        hour.insert(0, str(duration // 60))
        minute.insert(0, str(duration % 60))

        error = ctk.CTkLabel(dialog, text="", text_color="#F87171")
        error.pack(anchor="w", padx=26, pady=(8, 0))
        footer = ctk.CTkFrame(dialog, fg_color="transparent")
        footer.pack(fill="x", padx=24, pady=16)
        ctk.CTkButton(footer, text="Отмена", width=110, fg_color=self.PANEL_LIGHT, hover_color="#374151", command=dialog.destroy).pack(side="right", padx=(8, 0))
        def save_task():
            title = entry.get().strip()
            try:
                hours = int(hour.get() or 0)
                minutes = int(minute.get() or 0)
                if hours < 0 or minutes < 0 or minutes > 59 or hours > 23:
                    raise ValueError
            except ValueError:
                error.configure(text="Укажи часы от 0 до 23 и минуты от 0 до 59.")
                return
            if not title:
                error.configure(text="Введи название задачи.")
                return
            new_task = {"id": (task or {}).get("id", uuid.uuid4().hex), "focus": selected["focus"], "text": title, "duration_minutes": hours * 60 + minutes}
            current = self._selected_tasks()
            if task is not None:
                current = [item for item in current if item["id"] != task["id"]]
            current.append(new_task)
            self._write_selected_tasks(current)
            log_event("task_saved", f"{selected['focus']}: {title}")
            dialog.destroy()
        ctk.CTkButton(footer, text="Сохранить задачу", width=160, command=save_task).pack(side="right")
        entry.focus_set()

    def open_task_dialog(self) -> None:
        self._task_dialog()

    def _edit_task(self, task: dict[str, Any]) -> None:
        self._task_dialog(task)

    def _delete_task(self, task: dict[str, Any]) -> None:
        if not messagebox.askyesno("Удалить задачу", f"Удалить задачу «{task['text']}»?", parent=self.root):
            return
        self._write_selected_tasks([item for item in self._selected_tasks() if item["id"] != task["id"]])
        log_event("task_deleted", task["text"])

    def _refresh_ui(self) -> None:
        ctk = self.ctk
        for child in self.task_list_frame.winfo_children():
            child.destroy()
        self.status_label.configure(text=self.t("status_message"))
        tasks = self._selected_tasks()
        if not tasks:
            empty = ctk.CTkFrame(self.task_list_frame, fg_color=self.PANEL, corner_radius=16)
            empty.pack(fill="x", padx=4, pady=8)
            ctk.CTkLabel(empty, text="Пока задач нет", text_color=self.TEXT, font=ctk.CTkFont(size=17, weight="bold")).pack(pady=(22, 5))
            ctk.CTkLabel(empty, text=self.t("empty_schedule"), text_color=self.MUTED).pack(pady=(0, 22))
        for task in tasks:
            meta = FOCUS_LEVELS[task["focus"]]
            card = ctk.CTkFrame(self.task_list_frame, fg_color=self.PANEL, corner_radius=14)
            card.pack(fill="x", padx=4, pady=5)
            ctk.CTkLabel(card, text=meta["label"], fg_color=meta["color"], text_color="#111827", corner_radius=9, width=132, height=32, font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=14, pady=13)
            body = ctk.CTkFrame(card, fg_color="transparent")
            body.pack(side="left", fill="both", expand=True, padx=(2, 8), pady=10)
            ctk.CTkLabel(body, text=task["text"], text_color=self.TEXT, font=ctk.CTkFont(size=13, weight="bold"), anchor="w", justify="left", wraplength=500).pack(anchor="w")
            duration = int(task["duration_minutes"])
            duration_text = f"{duration // 60} ч {duration % 60} мин" if duration >= 60 else f"{duration} мин" if duration else "Без таймера"
            ctk.CTkLabel(body, text=duration_text, text_color=self.MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w", pady=(3, 0))
            buttons = ctk.CTkFrame(card, fg_color="transparent")
            buttons.pack(side="right", padx=10)
            ctk.CTkButton(buttons, text="Изменить", width=76, height=30, corner_radius=8, fg_color=self.PANEL_LIGHT, hover_color="#374151", command=lambda t=task: self._edit_task(t)).pack(pady=3)
            ctk.CTkButton(buttons, text="Удалить", width=76, height=30, corner_radius=8, fg_color="#7F1D1D", hover_color="#991B1B", command=lambda t=task: self._delete_task(t)).pack(pady=3)
        selected_name = DAY_NAMES[self.selected_date.weekday()].capitalize()
        self.date_label.configure(text=f"{self.selected_date.strftime('%d.%m.%Y')} · {selected_name}")
        today = datetime.now().date()
        controls_enabled = self.selected_date == today
        self.start_button.configure(state="normal" if controls_enabled else "disabled")
        self.pause_button.configure(state="normal" if controls_enabled and self.study_date == today.isoformat() else "disabled")
        self.check_button.configure(state="normal" if controls_enabled else "disabled")
        self.reset_timer_button.configure(state="normal" if controls_enabled and self.mode != "unlimited" else "disabled")
        self.root.title(f"Focus Guard · {selected_name}")

    def open_settings(self) -> None:
        if self._settings_window is not None:
            try:
                if self._settings_window.window.winfo_exists():
                    self._settings_window.window.lift()
                    return
            except Exception:
                pass
        from src.ui.settings_window import SettingsWindow
        self._settings_window = SettingsWindow(self.root, self.config, self._apply_settings)

    def _apply_settings(self, updated_config: dict[str, Any]) -> None:
        previous_rules = self.config.get("rules", {})
        previous_web = (bool(previous_rules.get("website_blocking_enabled", False)), tuple(previous_rules.get("blocked_websites", [])))
        self.config = updated_config
        self.ui_text = self.config["ui"]
        self.app_config = self.config["app"]
        self.root.title(self.t("window_title"))
        self.root.attributes("-topmost", bool(self.app_config.get("always_on_top", False)))
        self.root.geometry(f'{int(self.app_config.get("window_width", 1040))}x{int(self.app_config.get("window_height", 760))}')
        current_rules = self.config.get("rules", {})
        current_web = (bool(current_rules.get("website_blocking_enabled", False)), tuple(current_rules.get("blocked_websites", [])))
        if previous_web != current_web:
            try:
                request_admin_sync()
                messagebox.showinfo("Блокировка сайтов", "Запрошено применение правил сайтов. Подтверди запрос UAC Windows, если он появится.", parent=self.root)
            except Exception as exc:
                messagebox.showwarning("Блокировка сайтов", str(exc), parent=self.root)
        self._sync_tray()
        self._refresh_ui()
        self._update_timer_display(schedule_next=False)

    def _sync_tray(self) -> None:
        if self.app_config.get("show_in_tray", True):
            if self._tray is None:
                self._tray = SystemTrayController(
                    lambda: self.root.after(0, self._bring_to_front),
                    lambda: self.root.after(0, self.toggle_study_pause),
                    lambda: self.root.after(0, self._shutdown),
                )
            try:
                self._tray.start()
            except Exception as exc:
                self._tray = None
                messagebox.showwarning("Системный трей недоступен", f"Не удалось включить значок в трее: {exc}", parent=self.root)
        elif self._tray is not None:
            self._tray.stop()
            self._tray = None

    def _bring_to_front(self) -> None:
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except Exception:
            pass

    def _hide_to_tray_or_minimise(self) -> None:
        if self._tray is not None and self.app_config.get("show_in_tray", True):
            self.root.withdraw()
        else:
            self.root.iconify()

    def on_close(self) -> None:
        if self._tray is not None and self.app_config.get("show_in_tray", True) and self.app_config.get("close_to_tray", True):
            self.root.withdraw()
            return
        answer = messagebox.askyesno(self.t("exit_title"), self.t("exit_message"), parent=self.root)
        if answer:
            self._shutdown()

    def mark_study_started(self) -> None:
        if self.mode == "unlimited":
            return
        if not self._today_tasks():
            messagebox.showinfo("Список задач пуст", "Сначала добавь хотя бы одну задачу.", parent=self.root)
            return
        today = datetime.now().date().isoformat()
        if self.study_date != today:
            self.study_date, self.study_elapsed_seconds = today, 0
        if self.study_running_since is None:
            self.study_running_since = time.time()
        self.mode = "study"
        self._save_state()
        log_event("focus_started", "Учебный фокус запущен или продолжен")
        self._refresh_ui()
        self._update_timer_display(schedule_next=False)
        self.root.iconify()

    def toggle_study_pause(self) -> None:
        today = datetime.now().date().isoformat()
        if self.study_date != today:
            return
        if self.study_running_since is not None:
            self.study_elapsed_seconds = self._study_elapsed_seconds() or 0
            self.study_running_since = None
            log_event("focus_paused", "Учебный таймер приостановлен")
        else:
            self.study_running_since = time.time()
            self.mode = "study"
            log_event("focus_resumed", "Учебный таймер продолжен")
        self._save_state()
        self._refresh_ui()
        self._update_timer_display(schedule_next=False)

    def _study_elapsed_seconds(self) -> int | None:
        if self.study_date != datetime.now().date().isoformat():
            return None
        elapsed = max(0, int(self.study_elapsed_seconds))
        if self.study_running_since is not None:
            try:
                elapsed += max(0, int(time.time() - float(self.study_running_since)))
            except (TypeError, ValueError, OverflowError):
                pass
        return elapsed

    @staticmethod
    def _format_clock(seconds: int) -> str:
        hours, remainder = divmod(max(0, int(seconds)), 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def _format_duration(seconds: int) -> str:
        minutes = max(0, int(seconds)) // 60
        return f"{minutes // 60} ч {minutes % 60} мин" if minutes >= 60 else f"{minutes} мин"

    def _update_timer_display(self, schedule_next: bool = True) -> None:
        if not self.running:
            return
        if self.selected_date != datetime.now().date():
            self.timer_label.configure(text="Таймер фокуса доступен только для текущего дня.")
            if schedule_next:
                self.root.after(1000, self._update_timer_display)
            return
        required = required_study_minutes_for_today(self.config) * 60
        elapsed = self._study_elapsed_seconds()
        if elapsed is None:
            text = self.t("timer_not_started", required=self._format_clock(required))
        elif self.study_running_since is None:
            text = self.t("timer_paused_display", elapsed=self._format_clock(elapsed), required=self._format_clock(required))
        else:
            remaining = max(0, required - elapsed)
            text = self.t("timer_study_display", elapsed=self._format_clock(elapsed), required=self._format_clock(required), remaining=self._format_clock(remaining))
        self.timer_label.configure(text=text)
        if self.study_running_since is not None:
            self.pause_button.configure(text=self.t("pause_button"), state="normal")
        elif self.study_date == datetime.now().date().isoformat():
            self.pause_button.configure(text=self.t("resume_button"), state="normal")
        else:
            self.pause_button.configure(text=self.t("pause_button"), state="disabled")
        if schedule_next:
            self.root.after(1000, self._update_timer_display)

    def reset_study_timer(self) -> None:
        if self.mode == "unlimited":
            return
        if not messagebox.askyesno(self.t("reset_timer_title"), self.t("reset_timer_message"), parent=self.root):
            return
        self.study_date = None
        self.study_elapsed_seconds = 0
        self.study_running_since = None
        self.mode = "blocked"
        self._save_state()
        log_event("focus_reset", "Таймер фокуса сброшен")
        self._update_timer_display(schedule_next=False)

    def check_study_time(self) -> None:
        required = required_study_minutes_for_today(self.config) * 60
        tasks = self._today_tasks()
        if not tasks or required <= 0:
            messagebox.showinfo(self.t("check_no_tasks_title"), self.t("check_no_tasks_message"), parent=self.root)
            return
        elapsed = self._study_elapsed_seconds()
        if elapsed is None:
            messagebox.showinfo(self.t("check_no_session_title"), self.t("check_no_session_message", required=self._format_duration(required)), parent=self.root)
            return
        remaining = max(0, required - elapsed)
        if remaining:
            messagebox.showinfo(self.t("check_remaining_title"), self.t("check_remaining_message", elapsed=self._format_duration(elapsed), remaining=self._format_duration(remaining)), parent=self.root)
            log_event("focus_check_incomplete", f"Осталось {self._format_duration(remaining)}")
            return
        messagebox.showinfo(self.t("check_complete_title"), self.t("check_complete_message"), parent=self.root)
        self.mode = "unlimited"
        self._steam_seen = False
        self._steam_missing_since = None
        self._save_state()
        self._launch_steam_or_notify()
        self.root.iconify()

    def _launch_steam_or_notify(self) -> None:
        executable = get_steam_executable(self.config, self.detected_steam_path)
        if executable is None:
            messagebox.showwarning("Steam не найден", "Укажи путь к steam.exe в настройках.", parent=self.root)
            return
        try:
            flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0) if os.name == "nt" else 0
            subprocess.Popen([str(executable)], cwd=str(executable.parent), creationflags=flags)
        except Exception as exc:
            messagebox.showerror("Не удалось запустить Steam", str(exc), parent=self.root)

    def _find_processes(self, names: set[str]) -> list[Any]:
        if psutil is None:
            return []
        found = []
        for process in psutil.process_iter(attrs=["pid", "name", "exe"]):
            try:
                if (process.info.get("name") or "").casefold() in names:
                    found.append(process)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return found

    def _terminate_processes(self, processes: list[Any]) -> None:
        if psutil is None:
            return
        unique = {process.pid: process for process in processes}
        targets = list(unique.values())
        for process in targets:
            try:
                process.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        _, alive = psutil.wait_procs(targets, timeout=0.5)
        for process in alive:
            try:
                process.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

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
        if psutil is not None:
            app_rules = {str(name).casefold() for name in self.config.get("rules", {}).get("blocked_apps", [])}
            steam_names = {str(name).casefold() for name in self.app_config.get("steam_process_names", ["steam.exe"])}
            app_rules -= steam_names
            if app_rules:
                blocked = self._find_processes(app_rules)
                if blocked:
                    self._terminate_processes(blocked)
                    log_event("application_blocked", "Завершён процесс из списка ограничений")
            steam = self._find_processes(steam_names)
            if self.mode in ("blocked", "study") and steam:
                self._terminate_processes(steam)
                self.root.after(0, self._bring_to_front)
                log_event("steam_blocked", "Попытка запуска Steam во время фокуса")
            elif self.mode == "unlimited":
                if steam:
                    self._steam_seen = True
                    self._steam_missing_since = None
                elif self._steam_seen:
                    if self._steam_missing_since is None:
                        self._steam_missing_since = time.monotonic()
                    elif time.monotonic() - self._steam_missing_since >= 8:
                        self.mode = "blocked"
                        self._steam_seen = False
                        self._steam_missing_since = None
                        self._save_state()
                        log_event("steam_session_closed", "Steam закрыт; доступ снова ограничен")
        interval = max(200, min(10000, int(self.app_config.get("scan_interval_ms", 400))))
        self.root.after(interval, self._monitor_processes)

    def _shutdown(self) -> None:
        if not self.running:
            return
        self.running = False
        if self._tray is not None:
            self._tray.stop()
            self._tray = None
        log_event("application_closed", "Focus Guard закрыт пользователем")
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self) -> None:
        self.root.mainloop()
