@echo off
REM Start the deal/glitch watcher (runs continuously).
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python main.py --watch
pause
