@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   正在启动 JJYB AI智剪...
echo ========================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python 启动器 py。
    echo 请安装 Python 3，并勾选 Python Launcher。
    echo.
    pause
    exit /b 1
)

py -3 -u frontend\app.py
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" echo [错误] 应用启动失败，退出码：%EXIT_CODE%
pause
exit /b %EXIT_CODE%
