@echo off
REM Kai-Mirror (DRY) unified startup: server + monitor
cd /d "%~dp0"
echo Starting Kai-Mirror DRY server on port 8787...
start /b node server.js >server.log 2>&1
timeout /t 2 /nobreak >nul
echo Starting Kai-Mirror DRY monitor...
start /b node monitor.js >monitor.log 2>&1
echo Both started. Logs: server.log, monitor.log