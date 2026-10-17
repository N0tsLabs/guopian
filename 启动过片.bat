@echo off
cd /d "%~dp0"
title Guopian

rem Already High integrity? Then run.
whoami /groups | findstr /C:"S-1-16-12288" >nul 2>&1
if not errorlevel 1 goto :run

rem We are Medium or Low. Ask for elevation and hand over.
echo.
echo   Guopian needs permission to move files in your photo folders.
echo   A Windows prompt will appear - click Yes.
echo.
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b

:run
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo   [!] .venv\Scripts\python.exe not found.
  echo.
  echo   Create it first:
  echo       python -m venv .venv
  echo       .venv\Scripts\pip install -r requirements.txt
  echo.
  pause
  exit /b 1
)

echo.
echo   Starting Guopian...  (a window opens; close it to quit)
echo.
".venv\Scripts\python.exe" run.py %*

echo.
echo   Guopian closed.
pause
