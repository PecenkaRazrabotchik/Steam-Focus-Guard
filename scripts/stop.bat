@echo off
chcp 65001 >nul
py -3 "%~dp0..\main.py" --stop
pause
