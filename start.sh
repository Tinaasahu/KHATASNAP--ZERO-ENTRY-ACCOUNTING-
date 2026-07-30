#!/bin/bash
# KhataSnap — Unified Startup Script (Linux/Mac)

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

ROOT="$(cd "$(dirname "$0")" && pwd)"

# Activate venv if possible (best-effort; PYTHON variable is the real fix)
source "$ROOT/venv/bin/activate" 2>/dev/null || true

# Use the venv python & pip directly so modules are always found
PYTHON="$ROOT/venv/bin/python3"
PIP="$ROOT/venv/bin/pip"

BACKEND="$ROOT/Khatasnap"
FRONTEND="$ROOT/Khatasnap/frontend"

echo "================================================================"
echo "      KhataSnap — Unified Startup Script"
echo "================================================================"
echo

# If previous run left processes around, clear known ports first
echo "[0/6] Clearing stale services on known ports (8000-8004, 3000)..."
for port in 8000 8001 8002 8003 8004 3000; do
  pids=$(lsof -ti :"$port" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "  Killing existing process(es) on port $port: $pids"
    kill -9 $pids 2>/dev/null || true
  fi
done
echo "      Done."
echo

# Step 1: Install Python dependencies
echo "[1/6] Checking Python dependencies..."
"$PIP" install fastapi uvicorn python-dotenv httpx flask flask-cors numpy python-multipart 2>/dev/null
echo "      Done."
echo

# Step 2: Run migration
echo "[2/6] Running database migration..."
cd "$BACKEND"
"$PYTHON" migrate.py
echo

# Step 3: Start OCR Service (port 8001)
echo "[3/6] Starting OCR Service on port 8001..."
cd "$BACKEND" && "$PYTHON" services/ocr_service.py &
OCR_PID=$!
sleep 2

# Step 4: Start Voice Service (port 8002)
echo "[4/6] Starting Voice Service on port 8002..."
cd "$BACKEND/services"
[ ! -d node_modules ] && npm init -y && npm install express cors
VOICE_SERVICE_PORT=8002 node voice_service.js &
VOICE_PID=$!
cd "$BACKEND"
sleep 2

# Step 5: Start SRE + Inventory
echo "[5/6] Starting SRE (8003) + Inventory (8004)..."
"$PYTHON" services/sre_service.py &
SRE_PID=$!
"$PYTHON" services/inventory_service.py &
INV_PID=$!
sleep 2

# Step 6: Start Orchestrator (port 8000)
echo "[6/6] Starting Orchestrator on port 8000..."
"$PYTHON" orchestrator_api.py &
ORCH_PID=$!
sleep 3

# Step 7: Start Frontend (port 3000)
echo "Starting Frontend on port 3000..."
cd "$FRONTEND"
# Reinstall node_modules if vite binary is broken/missing
if [ ! -f node_modules/.bin/vite ] || ! node node_modules/.bin/vite --version &>/dev/null; then
  echo "  [Frontend] Reinstalling node_modules (vite binary broken or missing)..."
  rm -rf node_modules
  npm install
fi
npm run dev &
FE_PID=$!

# Save PIDs for stop script
echo "$OCR_PID $VOICE_PID $SRE_PID $INV_PID $ORCH_PID $FE_PID" > "$ROOT/.khatasnap_pids"

sleep 5

echo
echo "================================================================"
echo " Service Status:"
echo "───────────────────────────────────────────"
curl -sf http://127.0.0.1:8000/health >/dev/null && echo "  [OK] Orchestrator   - port 8000" || echo "  [!!] Orchestrator   - NOT READY"
curl -sf http://127.0.0.1:8001/health >/dev/null && echo "  [OK] OCR Service    - port 8001" || echo "  [!!] OCR Service    - NOT READY"
curl -sf http://127.0.0.1:8002/health >/dev/null && echo "  [OK] Voice Service  - port 8002" || echo "  [!!] Voice Service  - NOT READY"
curl -sf http://127.0.0.1:8003/health >/dev/null && echo "  [OK] SRE Service    - port 8003" || echo "  [!!] SRE Service    - NOT READY"
curl -sf http://127.0.0.1:8004/health >/dev/null && echo "  [OK] Inventory      - port 8004" || echo "  [!!] Inventory      - NOT READY"
echo "  [OK] Frontend       - port 3000"
echo "───────────────────────────────────────────"
echo
echo " Open http://localhost:3000 in your browser"
echo " Press Ctrl+C to stop all services"
echo

wait
