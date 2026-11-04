@echo off
chcp 65001 >nul
py -3 "%~dp0steam_focus_guard.py" --install-startup
pause
