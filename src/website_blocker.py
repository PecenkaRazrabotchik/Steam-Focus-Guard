"""Opt-in website blocking through a clearly marked Windows hosts-file section."""
from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from src.paths import DATA_DIR, PROJECT_ROOT

BEGIN_MARKER = "# >>> FOCUS GUARD MANAGED WEBSITE BLOCKS >>>"
END_MARKER = "# <<< FOCUS GUARD MANAGED WEBSITE BLOCKS <<<"
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$")


def normalise_domain(value: str) -> str:
    raw = value.strip().lower()
    raw = re.sub(r"^https?://", "", raw)
    raw = raw.split("/", 1)[0].split(":", 1)[0].strip(".")
    if raw.startswith("*.") or not raw:
        raise ValueError(f"Некорректный домен: {value}")
    try:
        domain = raw.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError(f"Некорректное имя сайта: {value}") from exc
    if not DOMAIN_RE.fullmatch(domain) or domain in {"localhost", "local"}:
        raise ValueError(f"Некорректный домен: {value}")
    return domain


def normalise_domains(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if str(value).strip():
            domain = normalise_domain(str(value))
            if domain not in result:
                result.append(domain)
    return result


def is_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def hosts_path() -> Path:
    if os.name != "nt":
        raise OSError("Блокировка сайтов через hosts поддерживается только в Windows.")
    root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return root / "System32" / "drivers" / "etc" / "hosts"


def _without_managed_section(text: str) -> str:
    start = text.find(BEGIN_MARKER)
    end = text.find(END_MARKER)
    if start == -1 and end == -1:
        return text.rstrip() + ("\n" if text else "")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Файл hosts содержит повреждённые маркеры Focus Guard. Автоматическое изменение отменено.")
    end += len(END_MARKER)
    return (text[:start].rstrip() + "\n" + text[end:].lstrip()).rstrip() + "\n"


def sync_hosts(domains: Iterable[str]) -> tuple[int, Path]:
    """Replace only Focus Guard's own marked section; preserve every other hosts entry."""
    if not is_admin():
        raise PermissionError("Для изменения файла hosts требуются права администратора Windows.")
    selected = normalise_domains(domains)
    path = hosts_path()
    original = path.read_text(encoding="utf-8", errors="surrogateescape") if path.exists() else ""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    backup = DATA_DIR / "hosts-before-focus-guard.bak"
    if original and not backup.exists():
        backup.write_text(original, encoding="utf-8", errors="surrogateescape")
    base = _without_managed_section(original)
    if selected:
        lines = [BEGIN_MARKER]
        for domain in selected:
            lines.append(f"0.0.0.0 {domain}")
            if not domain.startswith("www."):
                lines.append(f"0.0.0.0 www.{domain}")
        lines.append(END_MARKER)
        updated = base.rstrip() + "\n\n" + "\n".join(lines) + "\n"
    else:
        updated = base
    temp = path.with_suffix(".focus-guard.tmp")
    temp.write_text(updated, encoding="utf-8", errors="surrogateescape", newline="\n")
    temp.replace(path)
    subprocess.run(["ipconfig", "/flushdns"], capture_output=True, text=True, check=False)
    return len(selected), path


def request_admin_sync() -> None:
    """Run the narrowly scoped hosts-file sync under UAC; no hidden background elevation."""
    if is_admin():
        from src.config_manager import load_config
        config, error = load_config()
        if error:
            raise RuntimeError(error)
        rules = config.get("rules", {})
        domains = rules.get("blocked_websites", []) if rules.get("website_blocking_enabled") else []
        sync_hosts(domains)
        return
    if os.name != "nt":
        raise OSError("Блокировка сайтов доступна только в Windows.")
    if getattr(sys, "frozen", False):
        executable, params = sys.executable, "--sync-websites"
    else:
        executable, params = sys.executable, "-m src.website_blocker_cli"
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", executable, params, str(PROJECT_ROOT), 1
    )
    if result <= 32:
        raise OSError(f"Не удалось запросить права администратора (код {result}).")
