@echo off
REM First-time setup for Windows: creates the virtualenv and installs everything.
cd /d "%~dp0"
echo Creating virtual environment...
python -m venv .venv
call .venv\Scripts\activate.bat
echo Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dashboard.txt
if not exist .env copy .env.example .env
echo.
echo ============================================================
echo  Setup complete.
echo  1) Edit .env and add your API keys (Best Buy, eBay, Discord)
echo  2) Double-click run_watcher.bat  to start hunting
echo  3) Double-click run_dashboard.bat to open the web dashboard
echo ============================================================
pause
