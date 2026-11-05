"""Tkinter UI and Steam process guard controller."""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime
from typing import Any

try:
    import psutil
except ImportError:
    psutil = None

from src.config_manager import load_config
from src.paths import STATE_PATH, STOP_REQUEST_PATH
from src.scheduler import schedule_for_today, required_study_minutes_for_today
from src.steam_utils import get_steam_executable
from src.storage import log_event, save_json


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
        self.settings_window = None

        self.state = self._load_state()
        self.mode = self.state.get("mode", "blocked")
        if self.mode == "unlimited":
            # Unlimited permission is deliberately session-only and is not restored after a guard restart.
            self.mode = "blocked"
        self.study_date = self.state.get("study_date")
        self.study_elapsed_seconds = max(0, int(self.state.get("study_elapsed_seconds", 0) or 0))
        self.study_running_since = self.state.get("study_running_since")
        # Migrate legacy sessions that stored only their start timestamp.
        legacy_started_at = self.state.get("study_started_at")
        today = datetime.now().date().isoformat()
        if not self.study_date and legacy_started_at:
            try:
                legacy_start = float(legacy_started_at)
                if datetime.fromtimestamp(legacy_start).date().isoformat() == today:
                    self.study_date = today
                    self.study_running_since = legacy_start
            except (TypeError, ValueError, OSError, OverflowError):
                pass
        if self.study_date != today:
            self.study_date = None
            self.study_elapsed_seconds = 0
            self.study_running_since = None
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
        self._update_timer_display()
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
            "study_date": self.study_date,
            "study_elapsed_seconds": self.study_elapsed_seconds,
            "study_running_since": self.study_running_since,
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
        self.outer = tk.Frame(self.root, bg="#151820", padx=28, pady=18)
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
        self.date_label.pack(anchor="w", pady=(0, 12))

        self.timer_label = tk.Label(
            self.outer, text="", bg="#222936", fg="#f2f4f8",
            font=("Segoe UI", 12, "bold"), padx=12, pady=10,
            wraplength=560, justify="left"
        )
        self.timer_label.pack(fill="x", pady=(0, 12))

        self.status_label = tk.Label(
            self.outer, text="", bg="#222936", fg="#d9e2f2",
            font=("Segoe UI", 10), padx=12, pady=10, wraplength=560, justify="left"
        )
        self.status_label.pack(fill="x", pady=(0, 18))
        self.status_label.configure(text=self.t("status_message"))

        self.plan_heading = tk.Label(
            self.outer, text="", bg="#151820", fg="#f2f4f8",
            font=("Segoe UI", 12, "bold")
        )
        self.plan_heading.pack(anchor="w", pady=(0, 8))

        self.plan_box = tk.Text(
            self.outer, height=6, wrap="word", bg="#202632", fg="#e0e6ef",
            insertbackground="#e0e6ef", relief="flat", borderwidth=0,
            font=("Segoe UI", 11), padx=14, pady=12, spacing1=3, spacing3=7
        )
        self.plan_box.pack(fill="both", expand=True)
        self.plan_box.configure(state="disabled")

        self.action_frame = tk.Frame(self.outer, bg="#151820")
        self.action_frame.pack(fill="x", pady=(12, 0))

        self.primary_button = self._make_button(self.action_frame, "study_button", self.mark_study_started, primary=True)
        self.primary_button.pack(fill="x", pady=2)
        self.pause_button = self._make_button(self.action_frame, "pause_button", self.toggle_study_pause)
        self.pause_button.pack(fill="x", pady=2)
        self.check_button = self._make_button(self.action_frame, "check_button", self.check_study_time)
        self.check_button.pack(fill="x", pady=2)
        self.reset_timer_button = self._make_button(self.action_frame, "reset_timer_button", self.reset_study_timer)
        self.reset_timer_button.pack(fill="x", pady=2)
        self.settings_button = self._make_button(self.action_frame, "settings_button", self.open_settings)
        self.settings_button.pack(fill="x", pady=(8, 2))
        self.temporary_button = self._make_button(self.action_frame, "temporary_button", self.show_temporary_options)
        self.temporary_button.pack(fill="x", pady=2)

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
        self.footer_label.pack(anchor="w", pady=(10, 0))

    def open_settings(self) -> None:
        if self.settings_window is not None:
            try:
                if self.settings_window.window.winfo_exists():
                    self.settings_window.window.lift()
                    return
            except Exception:
                pass
        from src.ui.settings_window import SettingsWindow
        self.settings_window = SettingsWindow(self.root, self.config, self._apply_settings)

    def _apply_settings(self, updated_config: dict[str, Any]) -> None:
        self.config = updated_config
        self.ui_text = self.config["ui"]
        self.app_config = self.config["app"]
        self.root.title(self.t("window_title"))
        self.root.geometry(
            f'{int(self.app_config.get("window_width", 650))}x{int(self.app_config.get("window_height", 700))}'
        )
        self.root.attributes("-topmost", bool(self.app_config.get("always_on_top", True)))
        button_texts = (
            (self.primary_button, "study_button"),
            (self.check_button, "check_button"),
            (self.reset_timer_button, "reset_timer_button"),
            (self.settings_button, "settings_button"),
            (self.temporary_button, "temporary_button"),
            (self.temp_unlimited_button, "unlimited_button"),
            (self.temp_30_button, "thirty_minutes_button"),
            (self.back_button, "back_button"),
        )
        for button, key in button_texts:
            button.configure(text=self.t(key))
        self.temp_heading.configure(text=self.t("temporary_heading"))
        self.status_label.configure(text=self.t("status_message"))
        self._refresh_ui()
        self._update_timer_display(schedule_next=False)

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
        return schedule_for_today(self.config)

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

        # This label is intentionally static: users edit it in Settings.
        self.status_label.configure(text=self.t("status_message"))
        if hasattr(self, "pause_button"):
            is_running = self.study_running_since is not None and self.study_date == datetime.now().date().isoformat()
            has_session = is_running or self.study_date == datetime.now().date().isoformat()
            self.pause_button.configure(
                text=self.t("pause_button") if is_running else self.t("resume_button"),
                state="normal" if has_session else "disabled",
            )
        if hasattr(self, "reset_timer_button"):
            reset_available = self.mode not in ("timed", "unlimited")
            self.reset_timer_button.configure(state="normal" if reset_available else "disabled")
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
        self.action_frame.pack(before=self.footer_label, fill="x", pady=(12, 0))
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
        today = datetime.now().date().isoformat()
        if self.study_date != today:
            self.study_date = today
            self.study_elapsed_seconds = 0
            self.study_running_since = None
        if self.study_running_since is None:
            self.study_running_since = time.time()
        self.mode = "study"
        self._save_state()
        log_event("study_started", "Учебная сессия запущена или продолжена")
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
            log_event("study_paused", "Учебный таймер поставлен на паузу")
        else:
            self.study_running_since = time.time()
            self.mode = "study"
            log_event("study_resumed", "Учебный таймер продолжен")
        self._save_state()
        self._refresh_ui()
        self._update_timer_display(schedule_next=False)

    def _required_study_minutes_for_today(self) -> int:
        return required_study_minutes_for_today(self.config)

    def _study_elapsed_seconds(self) -> int | None:
        """Return accumulated study time, excluding every paused interval."""
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

    def _update_timer_display(self, schedule_next: bool = True) -> None:
        if not self.running:
            return
        required_seconds = self._required_study_minutes_for_today() * 60
        if self.mode == "timed" and self._timer_end is not None:
            remaining = max(0, int(self._timer_end - time.time()))
            text = self.t("timer_game_display", remaining=self._format_clock(remaining))
        else:
            elapsed = self._study_elapsed_seconds()
            if elapsed is None:
                text = self.t("timer_not_started", required=self._format_clock(required_seconds))
            else:
                remaining = max(0, required_seconds - elapsed)
                if self.study_running_since is None:
                    text = self.t(
                        "timer_paused_display",
                        elapsed=self._format_clock(elapsed),
                        required=self._format_clock(required_seconds),
                    )
                else:
                    text = self.t(
                        "timer_study_display",
                        elapsed=self._format_clock(elapsed),
                        required=self._format_clock(required_seconds),
                        remaining=self._format_clock(remaining),
                    )
        self.timer_label.configure(text=text)
        if schedule_next:
            self.root.after(1000, self._update_timer_display)

    def reset_study_timer(self) -> None:
        if self.mode in ("timed", "unlimited"):
            return
        confirmed = self.messagebox.askyesno(
            self.t("reset_timer_title"),
            self.t("reset_timer_message"),
            parent=self.root,
        )
        if not confirmed:
            return
        self.study_date = None
        self.study_elapsed_seconds = 0
        self.study_running_since = None
        if self.mode == "study":
            self.mode = "blocked"
        self._save_state()
        log_event("study_timer_reset", "Учебный таймер сброшен пользователем")
        self._refresh_ui()
        self._update_timer_display(schedule_next=False)

    @staticmethod
    def _format_duration(seconds: int) -> str:
        total_minutes = max(0, (int(seconds) + 59) // 60)
        hours, minutes = divmod(total_minutes, 60)
        if hours:
            return f"{hours} ч. {minutes} мин." if minutes else f"{hours} ч."
        return f"{minutes} мин."

    def check_study_time(self) -> None:
        """Check the configured study target and grant unlimited Steam access when reached."""
        required = self._required_study_minutes_for_today()
        elapsed_seconds = self._study_elapsed_seconds()

        if elapsed_seconds is None and required > 0:
            self.messagebox.showinfo(
                self.t("check_no_session_title"),
                self.t("check_no_session_message", required=self._format_duration(required * 60)),
                parent=self.root,
            )
            log_event("study_check_without_session", f"Дневная норма: {required} мин.")
            return

        elapsed_seconds = elapsed_seconds or 0
        required_seconds = required * 60
        remaining_seconds = max(0, required_seconds - elapsed_seconds)
        if remaining_seconds > 0:
            elapsed_text = self._format_duration(elapsed_seconds)
            required_text = self._format_duration(required_seconds)
            remaining_text = self._format_duration(remaining_seconds)
            message = self.t(
                "check_remaining_message",
                elapsed=elapsed_text,
                required=required_text,
                remaining=remaining_text,
            )
            self.messagebox.showinfo(
                self.t("check_remaining_title"),
                message,
                parent=self.root,
            )
            log_event(
                "study_check_remaining",
                f"Прошло {elapsed_text}; осталось {remaining_text}; норма {required_text}",
            )
            return

        elapsed_text = self._format_duration(elapsed_seconds)
        required_text = self._format_duration(required_seconds)
        self.messagebox.showinfo(
            self.t("check_complete_title"),
            self.t(
                "check_complete_message",
                elapsed=elapsed_text,
                required=required_text,
            ),
            parent=self.root,
        )
        log_event("study_requirement_met", f"Засчитано {elapsed_text}; норма {required_text}")
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
        self.study_date = None
        self.study_elapsed_seconds = 0
        self.study_running_since = None
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
        # The status message below the timer is user-editable and remains unchanged.
        
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
                    self.study_date = None
                    self.study_elapsed_seconds = 0
                    self.study_running_since = None
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
