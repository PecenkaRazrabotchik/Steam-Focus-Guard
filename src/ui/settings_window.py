"""Visual settings editor for schedule, Steam options and interface text."""
from __future__ import annotations

import copy
import shutil
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk
from typing import Any, Callable

from src.config_manager import DEFAULT_CONFIG, deep_merge
from src.paths import CONFIG_DIR, CONFIG_PATH, ensure_project_layout
from src.scheduler import DAY_KEYS, DAY_NAMES
from src.storage import save_json


class SettingsWindow:
    def __init__(
        self,
        parent: tk.Misc,
        config: dict[str, Any],
        on_save: Callable[[dict[str, Any]], None],
    ) -> None:
        self.parent = parent
        self.config = copy.deepcopy(config)
        self.on_save = on_save
        self.window = tk.Toplevel(parent)
        self.window.title("Настройки Steam Focus Guard")
        self.window.geometry("840x720")
        self.window.minsize(720, 580)
        self.window.transient(parent)

        self.day_names = {key: DAY_NAMES[index].capitalize() for index, key in enumerate(DAY_KEYS)}
        self.name_to_day = {name: key for key, name in self.day_names.items()}
        self.day_var = tk.StringVar(value=self.day_names[DAY_KEYS[0]])
        self.current_day_key = DAY_KEYS[0]
        self.required_var = tk.StringVar()
        self.task_entry_var = tk.StringVar()
        self.app_vars: dict[str, tk.Variable] = {}
        self.ui_vars: dict[str, tk.StringVar] = {}

        self._build()
        self._load_app()
        self._load_ui()
        self._load_day()

    def _build(self) -> None:
        root = ttk.Frame(self.window, padding=12)
        root.pack(fill="both", expand=True)
        tabs = ttk.Notebook(root)
        tabs.pack(fill="both", expand=True)

        self.schedule_tab = ttk.Frame(tabs, padding=12)
        self.app_tab = ttk.Frame(tabs, padding=12)
        self.ui_tab = ttk.Frame(tabs, padding=8)
        tabs.add(self.schedule_tab, text="Расписание")
        tabs.add(self.app_tab, text="Steam и приложение")
        tabs.add(self.ui_tab, text="Тексты интерфейса")

        self._build_schedule()
        self._build_app()
        self._build_ui_texts()

        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="Резервная копия", command=self.backup).pack(side="left")
        ttk.Button(actions, text="Сбросить настройки", command=self.reset).pack(side="left", padx=8)
        ttk.Button(actions, text="Отмена", command=self.window.destroy).pack(side="right")
        ttk.Button(actions, text="Сохранить", command=self.save).pack(side="right", padx=8)

    def _build_schedule(self) -> None:
        bar = ttk.Frame(self.schedule_tab)
        bar.pack(fill="x")
        ttk.Label(bar, text="День недели:").pack(side="left")
        self.day_combo = ttk.Combobox(
            bar,
            textvariable=self.day_var,
            values=[self.day_names[key] for key in DAY_KEYS],
            state="readonly",
            width=20,
        )
        self.day_combo.pack(side="left", padx=(8, 18))
        self.day_combo.bind("<<ComboboxSelected>>", self._switch_day)

        ttk.Label(bar, text="Норма, минут:").pack(side="left")
        ttk.Spinbox(bar, from_=0, to=1440, textvariable=self.required_var, width=8).pack(side="left", padx=8)
        ttk.Label(
            self.schedule_tab,
            text="Задачи выбранного дня. Пустые строки при сохранении пропускаются.",
        ).pack(anchor="w", pady=(16, 8))

        self.task_list = tk.Listbox(
            self.schedule_tab,
            height=14,
            selectmode=tk.SINGLE,
            bg="#202632",
            fg="#e0e6ef",
            selectbackground="#365d9b",
            relief="flat",
            highlightthickness=0,
        )
        self.task_list.pack(fill="both", expand=True)

        task_row = ttk.Frame(self.schedule_tab)
        task_row.pack(fill="x", pady=(10, 6))
        self.task_entry = ttk.Entry(task_row, textvariable=self.task_entry_var)
        self.task_entry.pack(side="left", fill="x", expand=True)
        self.task_entry.bind("<Return>", lambda _event: self.add_task())
        ttk.Button(task_row, text="Добавить задачу", command=self.add_task).pack(side="left", padx=(8, 0))

        actions = ttk.Frame(self.schedule_tab)
        actions.pack(fill="x")
        ttk.Button(actions, text="Удалить", command=self.remove_task).pack(side="left")
        ttk.Button(actions, text="Выше", command=lambda: self.move_task(-1)).pack(side="left", padx=8)
        ttk.Button(actions, text="Ниже", command=lambda: self.move_task(1)).pack(side="left")
        ttk.Label(
            self.schedule_tab,
            text="Особые даты сохраняются без изменений. Для их редактирования пока используй config/config.json.",
            wraplength=760,
        ).pack(anchor="w", pady=(14, 0))

    def _build_app(self) -> None:
        self.app_tab.columnconfigure(1, weight=1)
        fields = [
            ("steam_executable", "Путь к steam.exe (можно оставить пустым)"),
            ("scan_interval_ms", "Интервал проверки процессов, мс"),
            ("close_grace_seconds", "Задержка закрытия Steam, сек."),
            ("window_width", "Ширина главного окна"),
            ("window_height", "Высота главного окна"),
        ]
        for row, (key, label) in enumerate(fields):
            ttk.Label(self.app_tab, text=label).grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=9
            )
            variable = tk.StringVar()
            self.app_vars[key] = variable
            ttk.Entry(self.app_tab, textvariable=variable).grid(
                row=row, column=1, sticky="ew", pady=9
            )

        self.app_vars["launch_after_grant"] = tk.BooleanVar()
        self.app_vars["always_on_top"] = tk.BooleanVar()
        ttk.Checkbutton(
            self.app_tab,
            text="Автоматически запускать Steam после выдачи разрешения",
            variable=self.app_vars["launch_after_grant"],
        ).grid(row=len(fields), column=0, columnspan=2, sticky="w", pady=(18, 8))
        ttk.Checkbutton(
            self.app_tab,
            text="Показывать главное окно поверх остальных окон",
            variable=self.app_vars["always_on_top"],
        ).grid(row=len(fields) + 1, column=0, columnspan=2, sticky="w", pady=8)
        ttk.Label(
            self.app_tab,
            text="Интервал проверки не может быть меньше 100 мс. Установка слишком короткого интервала повышает нагрузку на систему.",
            wraplength=740,
        ).grid(row=len(fields) + 2, column=0, columnspan=2, sticky="w", pady=(24, 0))

    def _build_ui_texts(self) -> None:
        outer = ttk.Frame(self.ui_tab)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self.ui_inner = ttk.Frame(canvas, padding=8)
        self.ui_inner.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self.ui_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._load_ui()

    def _load_ui(self) -> None:
        for child in self.ui_inner.winfo_children():
            child.destroy()
        self.ui_vars.clear()
        ui = self.config.get("ui", {})
        visible_keys = [key for key in sorted(ui) if key != "all_done_button"]
        for row, key in enumerate(visible_keys):
            ttk.Label(self.ui_inner, text=key).grid(
                row=row, column=0, sticky="nw", padx=(0, 12), pady=5
            )
            variable = tk.StringVar(value=str(ui.get(key, "")))
            self.ui_vars[key] = variable
            ttk.Entry(self.ui_inner, textvariable=variable, width=72).grid(
                row=row, column=1, sticky="ew", pady=5
            )
        self.ui_inner.columnconfigure(1, weight=1)

    def _load_app(self) -> None:
        app = self.config.get("app", {})
        for key in (
            "steam_executable",
            "scan_interval_ms",
            "close_grace_seconds",
            "window_width",
            "window_height",
        ):
            self.app_vars[key].set(str(app.get(key, "")))
        for key in ("launch_after_grant", "always_on_top"):
            self.app_vars[key].set(bool(app.get(key, False)))

    def _load_day(self) -> None:
        key = self.name_to_day.get(self.day_var.get(), DAY_KEYS[0])
        self.current_day_key = key
        data = self.config.get("schedule", {}).get(key, {})
        self.required_var.set(str(data.get("required_study_minutes", 0)))
        self.task_list.delete(0, tk.END)
        for task in data.get("tasks", []):
            self.task_list.insert(tk.END, str(task))

    def _store_day(self) -> None:
        key = self.current_day_key
        try:
            required = int(self.required_var.get())
        except (TypeError, ValueError):
            raise ValueError("Дневная норма должна быть целым числом.")
        if not 0 <= required <= 1440:
            raise ValueError("Дневная норма должна быть от 0 до 1440 минут.")
        data = self.config.setdefault("schedule", {}).setdefault(key, {})
        data["required_study_minutes"] = required
        data["tasks"] = [
            self.task_list.get(index).strip()
            for index in range(self.task_list.size())
            if self.task_list.get(index).strip()
        ]

    def _switch_day(self, _event: Any = None) -> None:
        try:
            self._store_day()
        except ValueError as exc:
            self.day_var.set(self.day_names[self.current_day_key])
            messagebox.showerror("Некорректная норма", str(exc), parent=self.window)
            return
        self._load_day()

    def add_task(self) -> None:
        value = self.task_entry_var.get().strip()
        if value:
            self.task_list.insert(tk.END, value)
            self.task_entry_var.set("")
            self.task_entry.focus_set()

    def remove_task(self) -> None:
        selection = self.task_list.curselection()
        if selection:
            self.task_list.delete(selection[0])

    def move_task(self, direction: int) -> None:
        selection = self.task_list.curselection()
        if not selection:
            return
        index = selection[0]
        target = index + direction
        if target < 0 or target >= self.task_list.size():
            return
        value = self.task_list.get(index)
        self.task_list.delete(index)
        self.task_list.insert(target, value)
        self.task_list.selection_set(target)

    def reset(self) -> None:
        confirmed = messagebox.askyesno(
            "Сброс настроек",
            "Вернуть встроенные настройки по умолчанию? Текущие изменения вступят в силу только после сохранения.",
            parent=self.window,
        )
        if not confirmed:
            return
        self.config = copy.deepcopy(DEFAULT_CONFIG)
        self._load_app()
        self._load_ui()
        self._load_day()

    def backup(self) -> None:
        ensure_project_layout()
        backup_dir = CONFIG_DIR / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = backup_dir / f"config-{stamp}.json"
        if CONFIG_PATH.exists():
            shutil.copy2(CONFIG_PATH, backup_path)
        else:
            save_json(backup_path, self.config)
        messagebox.showinfo(
            "Резервная копия",
            f"Копия сохранена:\n{backup_path}",
            parent=self.window,
        )

    def save(self) -> None:
        try:
            self._store_day()
            app = self.config.setdefault("app", {})
            for key in ("scan_interval_ms", "close_grace_seconds", "window_width", "window_height"):
                try:
                    app[key] = int(self.app_vars[key].get())
                except (TypeError, ValueError):
                    raise ValueError(f"Параметр «{key}» должен быть целым числом.")
            if app["scan_interval_ms"] < 100:
                raise ValueError("Интервал проверки не может быть меньше 100 мс.")
            if app["close_grace_seconds"] < 0:
                raise ValueError("Задержка закрытия Steam не может быть отрицательной.")
            if app["window_width"] < 520 or app["window_height"] < 560:
                raise ValueError("Минимальный размер главного окна: 520 × 560.")
            app["steam_executable"] = self.app_vars["steam_executable"].get().strip()
            app["launch_after_grant"] = bool(self.app_vars["launch_after_grant"].get())
            app["always_on_top"] = bool(self.app_vars["always_on_top"].get())

            ui = self.config.setdefault("ui", {})
            ui.pop("all_done_button", None)
            for key, variable in self.ui_vars.items():
                ui[key] = variable.get()

            updated = deep_merge(DEFAULT_CONFIG, self.config)
            ensure_project_layout()
            backup_dir = CONFIG_DIR / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            if CONFIG_PATH.exists():
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                shutil.copy2(CONFIG_PATH, backup_dir / f"config-before-save-{stamp}.json")
            save_json(CONFIG_PATH, updated)
            self.on_save(updated)
            messagebox.showinfo("Настройки сохранены", "Изменения сохранены и применены.", parent=self.window)
            self.window.destroy()
        except (OSError, ValueError) as exc:
            messagebox.showerror("Не удалось сохранить настройки", str(exc), parent=self.window)
