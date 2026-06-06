@echo off
REM Start the local web dashboard, then open it in your browser.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
start "" http://127.0.0.1:5000
python dashboard.py
pause
