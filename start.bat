@echo off
rem Starts the watcher (under a supervisor that restarts it if it crashes) + dashboard server in the background.
rem Logs: data\watcher.log, data\supervisor.log
cd /d "%~dp0"
start "" .venv\Scripts\pythonw.exe -u watcher.py --supervise
start "" .venv\Scripts\pythonw.exe -u dashboard.py --no-open
