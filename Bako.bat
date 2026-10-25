@echo off
rem Starts the Bako desktop app. Double-click this file.
rem It uses the project's own Python, so no activate step is needed.
cd /d "%~dp0"
if not exist "agent\.venv\Scripts\python.exe" (
  echo Cannot find agent\.venv. Create it first, see the notes.
  pause
  exit /b 1
)
start "Bako" /min "agent\.venv\Scripts\python.exe" "agent\env\bako_app.py"
