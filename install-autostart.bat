@echo off
rem Runs start.bat at every Windows login.
echo @call "%~dp0start.bat" > "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\watcher.bat"
echo autostart installed
