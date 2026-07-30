# KhataSnap — Integration Architecture Guide

## Quick Start

### Backend & Microservices
```bash
# Windows
start.bat

# Linux/Mac
chmod +x start.sh
./start.sh
```

### Frontend (New React + Vite)
```bash
cd frontend
npm run dev
```

Then open **http://localhost:3000** (or the port Vite outputs) in your browser.

---

## Frontend Environment Variables
The frontend requires a `.env` file located at `frontend/.env` with the following configuration:
```env
VITE_API_BASE=http://localhost:8000
```
*(All API calls are routed via Axios to the Orchestrator, meaning no hardcoded localhost URLs inside the application logic).*

## Frontend Page to Backend Mapping
| Page Route | API Called | Backend Service |
|---|---|---|
| `/calculator` | `POST /api/calculator/entry` | Orchestrator (handles DB, SRE routing) |
| `/ocr` | `POST /api/ocr/upload`<br>`POST /api/ocr/confirm` | Port 8001 (OCR Engine) via Orchestrator |
| `/inventory` | `GET /api/inventory`<br>`POST /api/inventory/update` | Orchestrator (direct SQLite lookup) |
| **Global Voice Assistant** | `POST /api/voice/transcribe`<br>`POST /api/voice/confirm` | Port 8002 (Voice Node Engine) via Orchestrator |

---

## Architecture

```text
┌──────────────────────────────────────────────────────────────────┐
│  React Frontend (port 3000)                                      │
│  Base URL → import.meta.env.VITE_API_BASE                        │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  Orchestrator API (port 8000) — FastAPI                          │
│  ├─ /api/ocr/upload       → OCR Service (8001)                   │
│  ├─ /api/ocr/confirm      → SRE check → DB write → inventory    │
│  ├─ /api/voice/transcribe → Voice Service (8002)                 │
│  ├─ /api/calculator/entry → SRE pre-check                       │
│  └─ /api/inventory/*      — direct SQLite                        │
└──┬────────────────┬────────────────┬─────────────────────────────┘
   │                │                │
   ▼                ▼                ▼
┌────────┐   ┌────────────┐   ┌──────────┐
│  OCR   │   │   Voice    │   │   SRE    │
│  8001  │   │   8002     │   │   8003   │
│ FastAPI│   │  Express   │   │ FastAPI  │
└────────┘   └────────────┘   └──────────┘
```

## Data Flow Rules

1. **Every DB write** passes through SRE check first (`sre_flags`).
2. **Nothing is saved** until `confirmation_status == "confirmed"`.
3. **All services** communicate via JSON matching `DATA_CONTRACT.json`.
4. **The orchestrator** is the single entry point — frontend never talks directly to microservices.

## Database

**Single unified SQLite database**: `Khatasnap/khatasnap.db`

Key tables:
- `products` — full product catalog with SKU, price, stock
- `confirmed_bills` — all confirmed transactions (unified format)
- `stock_logs` — every stock change with audit trail
- `sre_flags_log` — all SRE flags for review
