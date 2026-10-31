@echo off
rem Stops every running Bako (the Python processes that run bako_app.py or dashboard.py). Safe to run any time.
powershell -NoProfile -Command "$n=0; Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and ($_.CommandLine -like '*bako_app.py*' -or $_.CommandLine -like '*dashboard.py*') -and $_.ProcessId -ne $PID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $n++ }; Write-Host ('Stopped ' + $n + ' Bako process(es).')"
