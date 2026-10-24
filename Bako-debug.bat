@echo off
rem Same as Bako.bat but keeps the console open so you can read any error.
cd /d "%~dp0"
"agent\.venv\Scripts\python.exe" "agent\env\bako_app.py"
pause
