# KhataSnap — Local Edition

Voice billing + OCR + Smart Reconciliation for kirana stores.
**Zero internet required. Everything stored in a single SQLite file.**

---

## Setup (one time)

```bash
pip install flask flask-cors
python app.py
```

Open `http://127.0.0.1:8000` in Chrome on the same device,
or `http://YOUR_LAN_IP:8000` on any phone on the same WiFi.

---

## Project Structure

```
khatasnap/
├── app.py              ← Flask server — all routes, SQLite backend
├── database.py         ← SQLite setup, seeds 15 demo products
├── helpers.py          ← Fuzzy match (5-level), SKU/TXN generators
├── sre_engine.py       ← Smart Reconciliation Engine (unchanged)
├── orchestrator.py     ← OCR pipeline orchestrator (optional)
├── pipeline/           ← 8-step OCR pipeline (needs paddleocr)
├── templates/
│   └── index.html      ← Mobile PWA (all 5 screens)
├── static/             ← CSS/JS assets (if any)
├── sre_memory.json     ← SRE learning memory (auto-created)
└── khatasnap.db        ← SQLite database (auto-created on first run)
```

---

## API Endpoints

| Method | Path | What it does |
|--------|------|--------------|
| GET  | `/api/products`          | All active products with categories |
| POST | `/api/products`          | Add new product |
| PUT  | `/api/products/<id>`     | Edit product |
| GET  | `/api/inventory`         | Inventory with stock status |
| GET  | `/api/inventory/logs`    | Stock change history |
| GET  | `/api/inventory/low-stock` | Items below min_stock |
| GET  | `/api/dashboard`         | Stats + today's revenue |
| POST | `/api/bills`             | Save completed bill + deduct stock |
| GET  | `/api/bills`             | Bill history |
| POST | `/api/ocr1`              | Sales bill items → deduct stock |
| POST | `/api/ocr2`              | Distributor bill items → add stock |
| POST | `/api/asr`               | Voice sale → deduct stock |
| POST | `/api/calculator`        | Calculator predictions → smart deduct |
| POST | `/api/ocr/scan`          | Upload receipt image → run OCR pipeline |
| POST | `/api/sre/smart/start`   | Start SRE reconciliation session |
| POST | `/api/sre/smart/answer`  | Answer SRE yes/no question |
| POST | `/api/sre/smart/learn`   | Confirm result, train memory |
| POST | `/api/sre/reconcile`     | Night stock correction |
| GET  | `/api/sre/conflicts`     | Pending uncertain mappings |

---

## How the Integration Works

```
Mobile Frontend (index.html)
        │
        │  loadProducts()      → GET /api/products
        │  checkout('Cash')    → POST /api/bills  → deducts stock
        │  demoVoice(cmd)      → POST /api/asr    → deducts stock
        │  demoOCR()           → POST /api/ocr1   → deducts stock
        │  buildStats()        → GET /api/dashboard + /api/sre/conflicts
        │  buildHistory()      → GET /api/inventory/logs
        │  openSreSheet()      → GET /api/sre/conflicts
        │                         POST /api/sre/smart/start
        │  sreConfirm()        → POST /api/sre/smart/learn
        ▼
    Flask (app.py)
        │
        ├── helpers.py         fuzzy_match (5-level: exact→substring→prefix→word→startswith)
        ├── database.py        SQLite: khatasnap.db  (no internet needed)
        ├── sre_engine.py      Bayesian + memory + warm-start
        └── pipeline/          OCR (optional: needs paddleocr)
```

---

## OCR Pipeline (Optional)

If you want real receipt scanning, install the OCR pipeline:

```bash
pip install paddleocr opencv-python Pillow pdf2image pdfplumber numpy
# Optional: install Ollama from https://ollama.com and run:
#   ollama pull glm-ocr
# Then /api/ocr/scan will use GLM-OCR (much better accuracy)
```

Without it, the app works fully — OCR just shows a demo response.

---

## Connecting Other Team APIs

The teammate APIs (OCR1 from Shashwat, ASR from Raj's voice pipeline, etc.)
simply POST to these endpoints:

```bash
# OCR1 (sales bill detected) → deduct stock
curl -X POST http://YOUR_IP:8000/api/ocr1 \
  -H "Content-Type: application/json" \
  -d '{"items":[{"name":"Parle G","qty":3},{"name":"Maggi","qty":2}]}'

# ASR (voice sale) → deduct stock
curl -X POST http://YOUR_IP:8000/api/asr \
  -H "Content-Type: application/json" \
  -d '{"name":"Parle G","qty":5}'

# Calculator (with confidence scores)
curl -X POST http://YOUR_IP:8000/api/calculator \
  -H "Content-Type: application/json" \
  -d '{"bill_total":50,"items":[{"name":"Parle G","qty":2,"price":10,"confidence":0.95}]}'
```
