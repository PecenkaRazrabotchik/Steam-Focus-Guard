"""Project paths and non-destructive migration from the legacy flat layout."""
from __future__ import annotations

import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
DOCS_DIR = PROJECT_ROOT / "docs"
CONFIG_PATH = CONFIG_DIR / "config.json"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "config.example.json"
STATE_PATH = DATA_DIR / "state.json"
LOG_PATH = DATA_DIR / "activity_log.csv"
LOCK_PATH = DATA_DIR / "guard.lock"
STOP_REQUEST_PATH = DATA_DIR / "stop.request"
LEGACY_FILES = (
    (PROJECT_ROOT / "state.json", STATE_PATH),
    (PROJECT_ROOT / "activity_log.csv", LOG_PATH),
    (PROJECT_ROOT / "guard.lock", LOCK_PATH),
    (PROJECT_ROOT / "stop.request", STOP_REQUEST_PATH),
)


def _copy_if_missing(source: Path, destination: Path) -> bool:
    if not source.is_file() or destination.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def ensure_project_layout() -> None:
    for directory in (CONFIG_DIR, DATA_DIR, SCRIPTS_DIR, DOCS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        if not _copy_if_missing(PROJECT_ROOT / "config.json", CONFIG_PATH):
            _copy_if_missing(DEFAULT_CONFIG_PATH, CONFIG_PATH)
    for source, destination in LEGACY_FILES:
        _copy_if_missing(source, destination)
