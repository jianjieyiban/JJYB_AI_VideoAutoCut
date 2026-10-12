@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   Starting JJYB AI SmartCut...
echo ========================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python Launcher was not found.
    echo Please install Python 3 and enable the Python Launcher.
    echo.
    pause
    exit /b 1
)

py -3 -X utf8 -u frontend\app.py
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" echo [ERROR] Application exited with code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
