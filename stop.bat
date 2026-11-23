@echo off
rem Stop the supervisor first so it doesn't restart the watcher we're about to stop.
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*watcher.py*--supervise*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }; Start-Sleep -Milliseconds 300; Get-CimInstance Win32_Process -Filter \"name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*watcher.py*' -or $_.CommandLine -like '*dashboard.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }"
echo watcher stopped
