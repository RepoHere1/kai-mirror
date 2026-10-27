#!/usr/bin/env bash
# Kai-Mirror (DRY) unified startup: server + monitor
cd "$(dirname "$0")"
echo "Starting Kai-Mirror DRY server on port 8787..."
node server.js </dev/null >server.log 2>&1 &
SERVER_PID=$!
sleep 2
echo "Starting Kai-Mirror DRY monitor..."
node monitor.js </dev/null >monitor.log 2>&1 &
MONITOR_PID=$!
echo "Server PID: $SERVER_PID, Monitor PID: $MONITOR_PID"
echo $SERVER_PID > .server.pid
echo $MONITOR_PID > .monitor.pid
echo "Both started. Logs: server.log, monitor.log"
wait