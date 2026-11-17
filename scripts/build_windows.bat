@echo off
setlocal
cd /d "%~dp0.."

echo ==========================================
echo  Focus Guard - Windows desktop build
echo ==========================================

py -m pip install -r requirements.txt
if errorlevel 1 goto :error

py -m PyInstaller --noconfirm --clean --windowed --onedir --name FocusGuard --collect-all customtkinter --collect-all pystray --collect-all PIL main.py
if errorlevel 1 goto :error

if not exist "dist\FocusGuard\config" mkdir "dist\FocusGuard\config"
if not exist "dist\FocusGuard\data" mkdir "dist\FocusGuard\data"
copy /Y "config\config.example.json" "dist\FocusGuard\config\config.example.json" >nul

echo.
echo Build completed: dist\FocusGuard\FocusGuard.exe
echo Keep the config and data folders beside the executable.
pause
exit /b 0

:error
echo.
echo Build failed. Read the error messages above.
pause
exit /b 1
