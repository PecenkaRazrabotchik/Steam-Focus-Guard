@echo off
chcp 65001 >nul
py -m pip install --user -r "%~dp0requirements.txt"
if errorlevel 1 (
  echo Не удалось установить зависимости. Проверь, что Python установлен и команда py доступна.
  pause
  exit /b 1
)
echo Зависимости установлены.
pause
