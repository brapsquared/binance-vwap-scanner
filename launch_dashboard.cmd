@echo off
setlocal
set "APP_DIR=C:\Users\Nebula PC\binance-vwap-scanner"
set "DASHBOARD_URL=http://127.0.0.1:8791"

curl.exe -fsS "%DASHBOARD_URL%/api/refresh-status" >nul 2>&1
if errorlevel 1 (
  start "VWAP Scanner Server" /min /D "%APP_DIR%" python app.py
  for /L %%I in (1,1,30) do (
    curl.exe -fsS "%DASHBOARD_URL%/api/refresh-status" >nul 2>&1 && goto :open
    timeout /t 1 /nobreak >nul
  )
  echo The VWAP Scanner server did not become ready within 30 seconds.
  pause
  exit /b 1
)

:open
start "" "%DASHBOARD_URL%"
exit /b 0
