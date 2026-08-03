@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   姝ｅ湪鍚姩 JJYB AI鏅哄壀...
echo ========================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo [閿欒] 鏈壘鍒?Python 鍚姩鍣?py銆?
    echo 璇峰畨瑁?Python 3锛屽苟鍕鹃€?Python Launcher銆?
    echo.
    pause
    exit /b 1
)

py -3 -u frontend\app.py
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" echo [閿欒] 搴旂敤鍚姩澶辫触锛岄€€鍑虹爜锛?EXIT_CODE%
pause
exit /b %EXIT_CODE%
