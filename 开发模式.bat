@echo off
rem Dev mode: a browser instead of the app window, with auto-reload.
rem Pure ASCII on purpose -- see the note in the other .bat.
cd /d "%~dp0"
title Guopian - dev

if not exist ".venv\Scripts\python.exe" (
  echo   [!] .venv\Scripts\python.exe not found.
  pause
  exit /b 1
)

echo.
echo   Dev mode. Open this in a browser:  http://127.0.0.1:8765
echo   Editing web/ reloads the page. Editing guopian/ restarts the server.
echo   Press Ctrl+C to quit.
echo.

".venv\Scripts\python.exe" run.py --dev --port 8765 %*

echo.
echo   Exited.
pause
