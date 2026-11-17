"""Elevated command used only to update Focus Guard's hosts-file section."""
from __future__ import annotations
import sys
from src.config_manager import load_config
from src.website_blocker import sync_hosts

def main() -> int:
    config, error = load_config()
    if error:
        print(error)
        return 1
    rules = config.get("rules", {})
    domains = rules.get("blocked_websites", []) if rules.get("website_blocking_enabled") else []
    try:
        count, path = sync_hosts(domains)
    except Exception as exc:
        print(f"Не удалось обновить блокировку сайтов: {exc}")
        return 1
    print(f"Обновлено доменов: {count}. Файл: {path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
