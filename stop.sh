#!/bin/bash
# KhataSnap — Stop All Services

ROOT="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$ROOT/.khatasnap_pids"

echo "Stopping all KhataSnap services..."

if [ -f "$PID_FILE" ]; then
    # PID file stores a space-separated list (single line). Kill each PID.
    for pid in $(cat "$PID_FILE"); do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
        fi
    done
    rm "$PID_FILE"
fi

# Kill any remaining processes on known ports
for port in 8000 8001 8002 8003 8004 3000; do
    pids=$(lsof -ti :"$port" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        kill -9 $pids 2>/dev/null || true
    fi
done

echo "All services stopped."
