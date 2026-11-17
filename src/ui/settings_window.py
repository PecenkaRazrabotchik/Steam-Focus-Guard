"""Modern settings window for application, blocking rules and Windows integration."""
from __future__ import annotations
import copy
import shutil
from datetime import datetime
from tkinter import messagebox
import customtkinter as ctk

from src.config_manager import DEFAULT_CONFIG, deep_merge, save_config
from src.paths import CONFIG_DIR, CONFIG_PATH, ensure_project_layout
from src.startup import install_startup, uninstall_startup
from src.website_blocker import normalise_domains

class SettingsWindow:
    def __init__(self, parent, config, on_save):
        self.parent = parent
        self.config = copy.deepcopy(config)
        self.on_save = on_save
        self.window = ctk.CTkToplevel(parent)
        self.window.title("Настройки · Focus Guard")
        self.window.geometry("780x690")
        self.window.minsize(680, 600)
        self.window.transient(parent)
        self.window.grab_set()
        self.app_vars = {}
        self._build()
        self._load()

    def _build(self):
        ctk.CTkLabel(self.window, text="Настройки", font=ctk.CTkFont(size=24, weight="bold")).pack(anchor="w", padx=24, pady=(22, 4))
        ctk.CTkLabel(self.window, text="Управляй ограничениями и поведением приложения", text_color="#9CA3AF").pack(anchor="w", padx=24, pady=(0, 16))
        self.tabs = ctk.CTkTabview(self.window, corner_radius=14, segmented_button_selected_color="#2563EB")
        self.tabs.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        self.apps_tab = self.tabs.add("Приложения")
        self.web_tab = self.tabs.add("Сайты")
        self.app_tab = self.tabs.add("Приложение")
        self._build_apps()
        self._build_websites()
        self._build_app_settings()
        actions = ctk.CTkFrame(self.window, fg_color="transparent")
        actions.pack(fill="x", padx=22, pady=(0, 18))
        ctk.CTkButton(actions, text="Резервная копия", width=150, fg_color="#374151", hover_color="#4B5563", command=self.backup).pack(side="left")
        ctk.CTkButton(actions, text="Отмена", width=110, fg_color="#374151", hover_color="#4B5563", command=self.window.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(actions, text="Сохранить", width=130, command=self.save).pack(side="right")

    def _build_apps(self):
        ctk.CTkLabel(self.apps_tab, text="Программы, которые будут закрываться при запуске", anchor="w", font=ctk.CTkFont(size=14, weight="bold")).pack(fill="x", padx=16, pady=(18, 8))
        self.apps_text = ctk.CTkTextbox(self.apps_tab, height=285, corner_radius=10)
        self.apps_text.pack(fill="both", expand=True, padx=16, pady=8)
        ctk.CTkLabel(self.apps_tab, text="Указывай имена процессов, по одному на строку: например, Discord.exe или Telegram.exe. Блокировка работает, пока запущен Focus Guard.", text_color="#9CA3AF", wraplength=660, justify="left").pack(fill="x", padx=16, pady=(8, 16))

    def _build_websites(self):
        self.web_enabled = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self.web_tab, text="Включить блокировку сайтов", variable=self.web_enabled, checkbox_width=20, checkbox_height=20).pack(anchor="w", padx=16, pady=(18, 12))
        ctk.CTkLabel(self.web_tab, text="Домены для блокировки", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(4, 8))
        self.web_text = ctk.CTkTextbox(self.web_tab, height=250, corner_radius=10)
        self.web_text.pack(fill="both", expand=True, padx=16, pady=8)
        ctk.CTkLabel(self.web_tab, text="Указывай домены без путей, по одному на строку: youtube.com. Применение изменяет только выделенный раздел в системном файле hosts и требует подтверждения UAC Windows. Остальные записи hosts сохраняются.", text_color="#9CA3AF", wraplength=660, justify="left").pack(fill="x", padx=16, pady=(8, 16))

    def _build_app_settings(self):
        tab = self.app_tab
        ctk.CTkLabel(tab, text="Поведение Focus Guard", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(18, 12))
        self.tray_var = ctk.BooleanVar()
        self.startup_var = ctk.BooleanVar()
        self.close_tray_var = ctk.BooleanVar()
        self.top_var = ctk.BooleanVar()
        ctk.CTkCheckBox(tab, text="Показывать значок в системном трее", variable=self.tray_var).pack(anchor="w", padx=16, pady=10)
        ctk.CTkCheckBox(tab, text="Запускать приложение вместе с Windows", variable=self.startup_var).pack(anchor="w", padx=16, pady=10)
        ctk.CTkCheckBox(tab, text="Сворачивать в трей при закрытии окна", variable=self.close_tray_var).pack(anchor="w", padx=16, pady=10)
        ctk.CTkCheckBox(tab, text="Показывать окно поверх других окон", variable=self.top_var).pack(anchor="w", padx=16, pady=10)
        ctk.CTkLabel(tab, text="Интервал проверки процессов (мс)", text_color="#9CA3AF").pack(anchor="w", padx=16, pady=(22, 4))
        self.scan_entry = ctk.CTkEntry(tab, width=150)
        self.scan_entry.pack(anchor="w", padx=16, pady=(0, 8))
        ctk.CTkLabel(tab, text="Постоянный текст под таймером", text_color="#9CA3AF").pack(anchor="w", padx=16, pady=(16, 4))
        self.status_message_entry = ctk.CTkEntry(tab, height=38, corner_radius=9)
        self.status_message_entry.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(tab, text="Сборка для Windows будет запускаться как отдельное приложение. Настройка автозапуска создаёт обычную запись в HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.", text_color="#9CA3AF", wraplength=660, justify="left").pack(anchor="w", padx=16, pady=(14, 10))

    def _load(self):
        rules = self.config.get("rules", {})
        self.apps_text.insert("1.0", "\n".join(rules.get("blocked_apps", [])))
        self.web_text.insert("1.0", "\n".join(rules.get("blocked_websites", [])))
        self.web_enabled.set(bool(rules.get("website_blocking_enabled", False)))
        app = self.config.get("app", {})
        self.tray_var.set(bool(app.get("show_in_tray", True)))
        self.startup_var.set(bool(app.get("start_with_windows", False)))
        self.close_tray_var.set(bool(app.get("close_to_tray", True)))
        self.top_var.set(bool(app.get("always_on_top", False)))
        self.scan_entry.insert(0, str(app.get("scan_interval_ms", 400)))
        self.status_message_entry.insert(0, str(self.config.get("ui", {}).get("status_message", "")))

    @staticmethod
    def _lines(widget):
        return [line.strip() for line in widget.get("1.0", "end").splitlines() if line.strip()]

    def backup(self):
        ensure_project_layout()
        folder = CONFIG_DIR / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = folder / f"config-before-settings-{stamp}.json"
        if CONFIG_PATH.exists():
            shutil.copy2(CONFIG_PATH, target)
        else:
            save_config(self.config)
            shutil.copy2(CONFIG_PATH, target)
        messagebox.showinfo("Резервная копия", f"Сохранено: {target}", parent=self.window)

    def save(self):
        try:
            blocked_apps = self._lines(self.apps_text)
            if any("/" in name or "\\" in name or not name.lower().endswith(".exe") for name in blocked_apps):
                raise ValueError("Для блокировки приложений указывай только имя процесса с расширением .exe, по одному на строку.")
            protected = {"system", "system idle process", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe", "smss.exe", "dwm.exe", "explorer.exe"}
            if any(name.casefold() in protected for name in blocked_apps):
                raise ValueError("В списке есть системный процесс, блокировка которого запрещена.")
            websites = normalise_domains(self._lines(self.web_text))
            scan_ms = int(self.scan_entry.get().strip())
            if scan_ms < 200 or scan_ms > 10000:
                raise ValueError("Интервал проверки должен быть от 200 до 10000 мс.")
            updated = copy.deepcopy(self.config)
            rules = updated.setdefault("rules", {})
            rules["blocked_apps"] = blocked_apps
            rules["blocked_websites"] = websites
            rules["website_blocking_enabled"] = bool(self.web_enabled.get())
            app = updated.setdefault("app", {})
            app["show_in_tray"] = bool(self.tray_var.get())
            app["start_with_windows"] = bool(self.startup_var.get())
            app["close_to_tray"] = bool(self.close_tray_var.get())
            app["always_on_top"] = bool(self.top_var.get())
            app["scan_interval_ms"] = scan_ms
            updated.setdefault("ui", {})["status_message"] = self.status_message_entry.get().strip()
            updated = deep_merge(DEFAULT_CONFIG, updated)
            if CONFIG_PATH.exists():
                folder = CONFIG_DIR / "backups"
                folder.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                shutil.copy2(CONFIG_PATH, folder / f"config-before-save-{stamp}.json")
            save_config(updated)
            startup_message = ""
            try:
                (install_startup if app["start_with_windows"] else uninstall_startup)()
            except Exception as exc:
                startup_message = f"\nНе удалось изменить автозапуск: {exc}"
            self.on_save(updated)
            messagebox.showinfo("Настройки сохранены", "Изменения сохранены." + startup_message, parent=self.window)
            self.window.destroy()
        except (OSError, ValueError) as exc:
            messagebox.showerror("Не удалось сохранить настройки", str(exc), parent=self.window)
