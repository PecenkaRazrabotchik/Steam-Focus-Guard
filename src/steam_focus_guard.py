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
from src.task_manager import (
    DEFAULT_CATEGORIES, FOCUS_LEVELS, PRIORITY_LEVELS, STATUS_LEVELS,
    normalize_tasks, sort_tasks,
)
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
        self.root.geometry("1280x880")
        self.root.minsize(980, 720)
        shell = ctk.CTkFrame(self.root, fg_color="transparent")
        shell.pack(fill="both", expand=True, padx=32, pady=24)

        # Header — title, description, date navigation and primary action.
        header = ctk.CTkFrame(shell, fg_color="transparent")
        header.pack(fill="x", pady=(0, 24))
        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(title_box, text="Task Manager", text_color="#F8FAFC", font=ctk.CTkFont(size=30, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(title_box, text="Организуй свои задачи и достигай целей", text_color="#9CA3AF", font=ctk.CTkFont(size=14)).pack(anchor="w", pady=(2, 8))
        date_row = ctk.CTkFrame(title_box, fg_color="transparent")
        date_row.pack(anchor="w")
        self.previous_day_button = ctk.CTkButton(date_row, text="‹", width=27, height=25, corner_radius=7, fg_color=self.PANEL_LIGHT, hover_color="#374151", command=lambda: self.change_selected_day(-1))
        self.previous_day_button.pack(side="left", padx=(0, 6))
        self.date_label = ctk.CTkLabel(date_row, text="", text_color="#94A3B8", font=ctk.CTkFont(size=11))
        self.date_label.pack(side="left")
        self.next_day_button = ctk.CTkButton(date_row, text="›", width=27, height=25, corner_radius=7, fg_color=self.PANEL_LIGHT, hover_color="#374151", command=lambda: self.change_selected_day(1))
        self.next_day_button.pack(side="left", padx=(6, 0))
        header_actions = ctk.CTkFrame(header, fg_color="transparent")
        header_actions.pack(side="right", anchor="n", pady=(7, 0))
        self.settings_button = ctk.CTkButton(header_actions, text="⚙", width=42, height=42, corner_radius=12, fg_color=self.PANEL_LIGHT, hover_color="#334155", command=self.open_settings)
        self.settings_button.pack(side="right", padx=(9, 0))
        self.add_task_button = ctk.CTkButton(header_actions, text="+  Новая задача", width=158, height=42, corner_radius=12, fg_color="#0891B2", hover_color="#2563EB", font=ctk.CTkFont(size=13, weight="bold"), command=self.open_task_dialog)
        self.add_task_button.pack(side="right")

        # Four dashboard metrics inspired by the reference design.
        stats = ctk.CTkFrame(shell, fg_color="transparent")
        stats.pack(fill="x", pady=(0, 18))
        for column in range(4):
            stats.grid_columnconfigure(column, weight=1, uniform="metric")
        self.metric_values = {}
        metric_specs = (
            ("total", "Всего задач", "#3B82F6", "▦"),
            ("completed", "Выполнено", "#10B981", "✓"),
            ("progress", "В работе", "#F59E0B", "◷"),
            ("urgent", "Срочные", "#EF4444", "↗"),
        )
        for column, (key, label, color, symbol) in enumerate(metric_specs):
            card = ctk.CTkFrame(stats, fg_color="#151E30", border_width=1, border_color="#253149", corner_radius=15, height=104)
            card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 10, 0 if column == 3 else 10))
            card.grid_propagate(False)
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=18, pady=(14, 3))
            ctk.CTkLabel(top, text=label, text_color="#8D98AB", font=ctk.CTkFont(size=11)).pack(side="left")
            ctk.CTkLabel(top, text=symbol, text_color=color, fg_color="#202B43", corner_radius=9, width=31, height=31, font=ctk.CTkFont(size=17, weight="bold")).pack(side="right")
            value = ctk.CTkLabel(card, text="0", text_color="#F8FAFC", font=ctk.CTkFont(size=25, weight="bold"))
            value.pack(anchor="w", padx=18, pady=(0, 8))
            self.metric_values[key] = value

        # Compact focus timer keeps existing pause/check/reset features without dominating the task board.
        focus_bar = ctk.CTkFrame(shell, fg_color="#151E30", border_width=1, border_color="#253149", corner_radius=14)
        focus_bar.pack(fill="x", pady=(0, 16))
        self.timer_label = ctk.CTkLabel(focus_bar, text="", text_color="#F8FAFC", font=ctk.CTkFont(size=14, weight="bold"), anchor="w")
        self.timer_label.pack(side="left", padx=16, pady=12, fill="x", expand=True)
        self.status_label = ctk.CTkLabel(focus_bar, text=self.t("status_message"), text_color="#94A3B8", font=ctk.CTkFont(size=10), anchor="e")
        self.status_label.pack(side="left", padx=8)
        self.start_button = ctk.CTkButton(focus_bar, text=self.t("study_button"), height=34, width=115, corner_radius=9, fg_color="#2563EB", hover_color="#1D4ED8", command=self.mark_study_started)
        self.start_button.pack(side="right", padx=(5, 12), pady=8)
        self.pause_button = ctk.CTkButton(focus_bar, text=self.t("pause_button"), height=34, width=92, corner_radius=9, fg_color=self.PANEL_LIGHT, hover_color="#374151", command=self.toggle_study_pause)
        self.pause_button.pack(side="right", padx=4, pady=8)
        self.check_button = ctk.CTkButton(focus_bar, text=self.t("check_button"), height=34, width=120, corner_radius=9, fg_color="#166534", hover_color="#15803D", command=self.check_study_time)
        self.check_button.pack(side="right", padx=4, pady=8)
        self.reset_timer_button = ctk.CTkButton(focus_bar, text="↺", height=34, width=38, corner_radius=9, fg_color=self.PANEL_LIGHT, hover_color="#374151", command=self.reset_study_timer)
        self.reset_timer_button.pack(side="right", padx=4, pady=8)

        # Search and filters.
        filter_panel = ctk.CTkFrame(shell, fg_color="#151E30", border_width=1, border_color="#29354A", corner_radius=15)
        filter_panel.pack(fill="x", pady=(0, 18))
        filter_row = ctk.CTkFrame(filter_panel, fg_color="transparent")
        filter_row.pack(fill="x", padx=14, pady=12)
        self.search_var = ctk.StringVar()
        self.search_entry = ctk.CTkEntry(filter_row, textvariable=self.search_var, height=42, corner_radius=10, border_color="#354258", fg_color="#1B2639", placeholder_text="⌕  Поиск задач...")
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.search_entry.bind("<KeyRelease>", lambda _event: self._refresh_ui())
        self.status_filter_var = ctk.StringVar(value="Все статусы")
        self.priority_filter_var = ctk.StringVar(value="Все приоритеты")
        self.category_filter_var = ctk.StringVar(value="Все категории")
        self.status_filter = ctk.CTkOptionMenu(filter_row, variable=self.status_filter_var, values=["Все статусы"] + [meta["label"] for meta in STATUS_LEVELS.values()], width=142, height=42, corner_radius=10, fg_color="#202B3E", button_color="#2D3A50", button_hover_color="#3A4961", command=lambda _value: self._refresh_ui())
        self.status_filter.pack(side="left", padx=4)
        self.priority_filter = ctk.CTkOptionMenu(filter_row, variable=self.priority_filter_var, values=["Все приоритеты"] + [meta["label"] for meta in PRIORITY_LEVELS.values()], width=154, height=42, corner_radius=10, fg_color="#202B3E", button_color="#2D3A50", button_hover_color="#3A4961", command=lambda _value: self._refresh_ui())
        self.priority_filter.pack(side="left", padx=4)
        self.category_filter = ctk.CTkOptionMenu(filter_row, variable=self.category_filter_var, values=["Все категории"] + list(DEFAULT_CATEGORIES), width=145, height=42, corner_radius=10, fg_color="#202B3E", button_color="#2D3A50", button_hover_color="#3A4961", command=lambda _value: self._refresh_ui())
        self.category_filter.pack(side="left", padx=(4, 0))

        self.task_list_frame = ctk.CTkScrollableFrame(shell, fg_color="transparent", corner_radius=14)
        self.task_list_frame.pack(fill="both", expand=True)
        for column in range(3):
            self.task_list_frame.grid_columnconfigure(column, weight=1, uniform="task-card")
        ctk.CTkLabel(shell, text=self.t("footer_hint"), text_color="#68758B", font=ctk.CTkFont(size=10)).pack(anchor="w", pady=(12, 0))

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
        dialog.geometry("690x610")
        dialog.minsize(640, 570)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        selected_focus = {"value": (task or {}).get("focus", "main")}
        ctk.CTkLabel(dialog, text="Новая задача" if task is None else "Редактирование задачи", font=ctk.CTkFont(size=23, weight="bold")).pack(anchor="w", padx=26, pady=(22, 4))
        ctk.CTkLabel(dialog, text="Опиши задачу, выбери фокус и настрой детали.", text_color=self.MUTED).pack(anchor="w", padx=26, pady=(0, 18))

        focus_panel = ctk.CTkFrame(dialog, fg_color=self.PANEL, corner_radius=13)
        focus_panel.pack(fill="x", padx=24, pady=(0, 14))
        ctk.CTkLabel(focus_panel, text="ФОКУС", text_color=self.MUTED, font=ctk.CTkFont(size=10, weight="bold")).pack(anchor="w", padx=14, pady=(12, 7))
        focus_row = ctk.CTkFrame(focus_panel, fg_color="transparent")
        focus_row.pack(fill="x", padx=10, pady=(0, 12))
        focus_badge = ctk.CTkLabel(focus_row, text="", width=132, height=37, corner_radius=9, text_color="#111827", font=ctk.CTkFont(size=11, weight="bold"))
        focus_badge.pack(side="left", padx=4)
        focus_buttons = {}
        def select_focus(level: str) -> None:
            selected_focus["value"] = level
            meta = FOCUS_LEVELS[level]
            focus_badge.configure(text=meta["label"], fg_color=meta["color"])
            for key, button in focus_buttons.items():
                button.configure(border_width=2 if key == level else 0, border_color=meta["color"] if key == level else self.PANEL_LIGHT)
        for level in ("main", "additional", "later"):
            meta = FOCUS_LEVELS[level]
            button = ctk.CTkButton(focus_row, text=meta["label"], height=37, corner_radius=9, fg_color="#263449", hover_color="#334155", text_color=meta["color"], command=lambda value=level: select_focus(value))
            button.pack(side="left", fill="x", expand=True, padx=4)
            focus_buttons[level] = button
        select_focus(selected_focus["value"])

        form = ctk.CTkFrame(dialog, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=26)
        ctk.CTkLabel(form, text="Название задачи", text_color="#CBD5E1", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(3, 6))
        entry = ctk.CTkEntry(form, height=42, corner_radius=10, placeholder_text="Например: Подготовить проектное предложение")
        entry.pack(fill="x")
        entry.insert(0, (task or {}).get("text", ""))

        metadata = ctk.CTkFrame(form, fg_color="transparent")
        metadata.pack(fill="x", pady=(15, 0))
        for column in range(3):
            metadata.grid_columnconfigure(column, weight=1)
        status_label_to_key = {meta["label"]: key for key, meta in STATUS_LEVELS.items()}
        priority_label_to_key = {meta["label"]: key for key, meta in PRIORITY_LEVELS.items()}
        current_status = (task or {}).get("status", "todo")
        current_priority = (task or {}).get("priority", "medium")
        status_var = ctk.StringVar(value=STATUS_LEVELS.get(current_status, STATUS_LEVELS["todo"])["label"])
        priority_var = ctk.StringVar(value=PRIORITY_LEVELS.get(current_priority, PRIORITY_LEVELS["medium"])["label"])
        category_var = ctk.StringVar(value=(task or {}).get("category", "Учёба"))
        ctk.CTkLabel(metadata, text="Статус", text_color=self.MUTED).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 5))
        ctk.CTkLabel(metadata, text="Приоритет", text_color=self.MUTED).grid(row=0, column=1, sticky="w", padx=8, pady=(0, 5))
        ctk.CTkLabel(metadata, text="Категория", text_color=self.MUTED).grid(row=0, column=2, sticky="w", padx=(8, 0), pady=(0, 5))
        status_menu = ctk.CTkOptionMenu(metadata, variable=status_var, values=list(status_label_to_key), height=38, corner_radius=9, fg_color="#263449", button_color="#334155", button_hover_color="#475569")
        status_menu.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        priority_menu = ctk.CTkOptionMenu(metadata, variable=priority_var, values=list(priority_label_to_key), height=38, corner_radius=9, fg_color="#263449", button_color="#334155", button_hover_color="#475569")
        priority_menu.grid(row=1, column=1, sticky="ew", padx=8)
        category_entry = ctk.CTkEntry(metadata, textvariable=category_var, height=38, corner_radius=9, placeholder_text="Своя категория")
        category_entry.grid(row=1, column=2, sticky="ew", padx=(8, 0))

        ctk.CTkLabel(form, text="Планируемое время", text_color="#CBD5E1", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", pady=(17, 6))
        timing = ctk.CTkFrame(form, fg_color="transparent")
        timing.pack(fill="x")
        hour = ctk.CTkEntry(timing, width=90, height=38, corner_radius=9, placeholder_text="Часы")
        hour.pack(side="left", padx=(0, 8))
        minute = ctk.CTkEntry(timing, width=90, height=38, corner_radius=9, placeholder_text="Минуты")
        minute.pack(side="left")
        duration = int((task or {}).get("duration_minutes", 0))
        hour.insert(0, str(duration // 60))
        minute.insert(0, str(duration % 60))
        error = ctk.CTkLabel(form, text="", text_color="#F87171", anchor="w")
        error.pack(fill="x", pady=(8, 0))

        footer = ctk.CTkFrame(dialog, fg_color="transparent")
        footer.pack(fill="x", padx=24, pady=18)
        ctk.CTkButton(footer, text="Отмена", width=110, height=40, corner_radius=9, fg_color=self.PANEL_LIGHT, hover_color="#374151", command=dialog.destroy).pack(side="right", padx=(8, 0))
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
            category = category_var.get().strip() or "Другое"
            new_task = {
                "id": (task or {}).get("id", uuid.uuid4().hex),
                "focus": selected_focus["value"],
                "text": title,
                "duration_minutes": hours * 60 + minutes,
                "status": status_label_to_key[status_var.get()],
                "priority": priority_label_to_key[priority_var.get()],
                "category": category,
            }
            current = self._selected_tasks()
            if task is not None:
                current = [item for item in current if item["id"] != task["id"]]
            current.append(new_task)
            self._write_selected_tasks(current)
            log_event("task_saved", f"{selected_focus['value']}/{new_task['priority']}/{new_task['status']}: {title}")
            dialog.destroy()
        ctk.CTkButton(footer, text="Сохранить задачу", width=160, height=40, corner_radius=9, fg_color="#0891B2", hover_color="#2563EB", command=save_task).pack(side="right")
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

        # Update metrics before filtering so they always describe the full selected-day list.
        counts = {
            "total": len(tasks),
            "completed": sum(task.get("status") == "done" for task in tasks),
            "progress": sum(task.get("status") == "in_progress" for task in tasks),
            "urgent": sum(task.get("priority") == "urgent" and task.get("status") != "done" for task in tasks),
        }
        for key, value in counts.items():
            self.metric_values[key].configure(text=str(value))

        # Refresh category choices while retaining a valid current selection.
        categories = sorted({str(task.get("category", "Другое")) for task in tasks}, key=str.casefold)
        category_values = ["Все категории"] + categories
        current_category = self.category_filter_var.get()
        self.category_filter.configure(values=category_values)
        if current_category not in category_values:
            self.category_filter_var.set("Все категории")

        search = self.search_var.get().strip().casefold()
        status_filter = self.status_filter_var.get()
        priority_filter = self.priority_filter_var.get()
        category_filter = self.category_filter_var.get()
        status_lookup = {meta["label"]: key for key, meta in STATUS_LEVELS.items()}
        priority_lookup = {meta["label"]: key for key, meta in PRIORITY_LEVELS.items()}
        visible = []
        for task in tasks:
            if search and search not in task["text"].casefold() and search not in task.get("category", "").casefold():
                continue
            if status_filter != "Все статусы" and task.get("status") != status_lookup.get(status_filter):
                continue
            if priority_filter != "Все приоритеты" and task.get("priority") != priority_lookup.get(priority_filter):
                continue
            if category_filter != "Все категории" and task.get("category") != category_filter:
                continue
            visible.append(task)

        if not tasks:
            empty = ctk.CTkFrame(self.task_list_frame, fg_color="#151E30", border_width=1, border_color="#29354A", corner_radius=16)
            empty.grid(row=0, column=0, columnspan=3, sticky="ew", padx=4, pady=8)
            ctk.CTkLabel(empty, text="Пока задач нет", text_color=self.TEXT, font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(28, 5))
            ctk.CTkLabel(empty, text="Нажми «Новая задача», чтобы добавить первое дело.", text_color=self.MUTED).pack(pady=(0, 28))
        elif not visible:
            empty = ctk.CTkFrame(self.task_list_frame, fg_color="#151E30", border_width=1, border_color="#29354A", corner_radius=16)
            empty.grid(row=0, column=0, columnspan=3, sticky="ew", padx=4, pady=8)
            ctk.CTkLabel(empty, text="Задачи не найдены", text_color=self.TEXT, font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(24, 4))
            ctk.CTkLabel(empty, text="Измени поисковый запрос или параметры фильтрации.", text_color=self.MUTED).pack(pady=(0, 24))

        for index, task in enumerate(visible):
            row, column = divmod(index, 3)
            self._render_task_card(task, row, column)

        selected_name = DAY_NAMES[self.selected_date.weekday()].capitalize()
        self.date_label.configure(text=f"{self.selected_date.strftime('%d.%m.%Y')} · {selected_name}")
        today = datetime.now().date()
        controls_enabled = self.selected_date == today
        self.start_button.configure(state="normal" if controls_enabled else "disabled")
        self.pause_button.configure(state="normal" if controls_enabled and self.study_date == today.isoformat() else "disabled")
        self.check_button.configure(state="normal" if controls_enabled else "disabled")
        self.reset_timer_button.configure(state="normal" if controls_enabled and self.mode != "unlimited" else "disabled")
        self.root.title(f"Task Manager · {selected_name}")

    def _render_task_card(self, task: dict[str, Any], row: int, column: int) -> None:
        ctk = self.ctk
        focus_meta = FOCUS_LEVELS[task.get("focus", "later")]
        status_meta = STATUS_LEVELS.get(task.get("status"), STATUS_LEVELS["todo"])
        priority_meta = PRIORITY_LEVELS.get(task.get("priority"), PRIORITY_LEVELS["medium"])
        card = ctk.CTkFrame(self.task_list_frame, fg_color="#182235", border_width=1, border_color="#2A354B", corner_radius=14)
        card.grid(row=row, column=column, sticky="nsew", padx=5, pady=6)
        accent = ctk.CTkFrame(card, width=4, corner_radius=0, fg_color=priority_meta["color"])
        accent.pack(side="left", fill="y", padx=(0, 11))
        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(side="left", fill="both", expand=True, padx=(0, 10), pady=12)
        header = ctk.CTkFrame(content, fg_color="transparent")
        header.pack(fill="x")
        title_font = ctk.CTkFont(size=14, weight="bold", overstrike=task.get("status") == "done")
        ctk.CTkLabel(header, text=task["text"], text_color="#E5E7EB" if task.get("status") != "done" else "#8B95A6", font=title_font, anchor="w", justify="left", wraplength=310).pack(side="left", fill="x", expand=True)
        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.pack(side="right", padx=(4, 0))
        ctk.CTkButton(actions, text="✎", width=27, height=25, corner_radius=7, fg_color="#263449", hover_color="#3A4961", command=lambda t=task: self._edit_task(t)).pack(side="left", padx=2)
        ctk.CTkButton(actions, text="×", width=27, height=25, corner_radius=7, fg_color="#3B2630", hover_color="#65303D", text_color="#FCA5A5", command=lambda t=task: self._delete_task(t)).pack(side="left", padx=2)

        tags = ctk.CTkFrame(content, fg_color="transparent")
        tags.pack(fill="x", pady=(10, 8))
        badges = (
            (focus_meta["label"], focus_meta["color"]),
            (status_meta["label"], status_meta["color"]),
            (priority_meta["label"], priority_meta["color"]),
            (task.get("category", "Другое"), "#A78BFA"),
        )
        for label, color in badges:
            chip = ctk.CTkLabel(tags, text=label, text_color=color, fg_color="#222E43", corner_radius=8, font=ctk.CTkFont(size=9, weight="bold"), padx=7, pady=4)
            chip.pack(side="left", padx=(0, 5))
        duration = int(task.get("duration_minutes", 0))
        if duration >= 60:
            duration_text = f"{duration // 60} ч" + (f" {duration % 60} мин" if duration % 60 else "")
        else:
            duration_text = f"{duration} мин"
        duration_row = ctk.CTkFrame(content, fg_color="transparent")
        duration_row.pack(fill="x")
        ctk.CTkLabel(duration_row, text=f"◷  {duration_text if duration else 'Без таймера'}", text_color="#9CA3AF", font=ctk.CTkFont(size=11)).pack(side="left")

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
        if not self.app_config.get("launch_after_grant", True):
            return
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
            # User-selected distracting applications are blocked only during focus,
            # not after the daily plan has been completed and access is granted.
            if self.mode in ("blocked", "study") and app_rules:
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
                    elif time.monotonic() - self._steam_missing_since >= float(self.app_config.get("close_grace_seconds", 8)):
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
