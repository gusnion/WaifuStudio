@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m app.health %*
pause
