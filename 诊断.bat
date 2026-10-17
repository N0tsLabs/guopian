@echo off
cd /d "%~dp0"
title Guopian - diagnosis
".venv\Scripts\python.exe" "scripts\diagnose.py"
echo.
pause
