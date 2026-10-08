@echo off
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 station_server.py --open
) else (
  python station_server.py --open
)
echo.
echo If Python was not found, install Python 3 and run this file again.
pause
