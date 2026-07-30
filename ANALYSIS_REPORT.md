# KhataSnap — PHASE 1 ANALYSIS REPORT

> **Generated**: 2026-04-12
> **Status**: Complete — DO NOT write code until this report is reviewed.

---

## 1. Complete File Inventory

### Root: `Backup for khatasnap/`

| # | Path | Language | Description |
|---|------|----------|-------------|
| 1 | `Khatasnap/app.py` | Python | **Main Flask server** — 1155 lines, all API routes on port 8000 |
| 2 | `Khatasnap/database.py` | Python | SQLite schema + seed data (15 products, 6 suppliers, 12 categories) |
| 3 | `Khatasnap/helpers.py` | Python | SKU generation, 5-level fuzzy match, transaction ID generator |
| 4 | `Khatasnap/sre_engine.py` | Python | Smart Reconciliation Engine v5 — Bayesian + memory + warm-start (847 lines) |
| 5 | `Khatasnap/orchestrator.py` | Python | OCR pipeline orchestrator — VLM mode or PaddleOCR fallback |
| 6 | `Khatasnap/VoiceInput.jsx` | JSX | Standalone copy of VoiceInput component (likely stale) |
| 7 | `Khatasnap/khatasnap.db` | SQLite | Live database (77KB) |
| 8 | `Khatasnap/README.md` | Markdown | README for Flask app |

### OCR Pipeline: `Khatasnap/pipeline/`

| # | Path | Language | Description |
|---|------|----------|-------------|
| 9 | `pipeline/__init__.py` | Python | Package init |
| 10 | `pipeline/step1_quality.py` | Python | Image quality analysis |
| 11 | `pipeline/step2_enhance.py` | Python | Image enhancement |
| 12 | `pipeline/step3_document.py` | Python | Perspective correction + cropping |
| 13 | `pipeline/step4_ocr.py` | Python | PaddleOCR + Ollama GLM-OCR |
| 14 | `pipeline/step5_layout.py` | Python | Row grouping |
| 15 | `pipeline/step6_extract.py` | Python | Regex extraction of items/GST |
| 16 | `pipeline/step7_confidence.py` | Python | Confidence scoring |
| 17 | `pipeline/step8_input.py` | Python | Image/PDF input loader |

### SRE with Inventory (Rizvan): `SREwithInventory/SRE_new/SRE_upgraded/`

| # | Path | Language | Description |
|---|------|----------|-------------|
| 18 | `SRE_upgraded/app.py` | Python | Standalone Flask SRE+Inventory server (50KB), Supabase PostgreSQL |
| 19 | `SRE_upgraded/database.py` | Python | PostgreSQL connection via psycopg2 |
| 20 | `SRE_upgraded/helpers.py` | Python | SKU/fuzzy helpers (different from main) |
| 21 | `SRE_upgraded/sre_engine.py` | Python | Duplicate of main sre_engine.py |
| 22 | `SRE_upgraded/.env` | Config | PostgreSQL credentials |
| 23 | `SRE_upgraded/sre_memory.json` | JSON | SRE memory state |
| 24-28 | `SRE_upgraded/static/`, `templates/` | CSS/JS/HTML | SRE frontend (11 HTML templates) |

### Standalone OCR Service: `khatasnap_ocr/`

| # | Path | Language | Description |
|---|------|----------|-------------|
| 29 | `khatasnap_ocr/main.py` | Python | FastAPI OCR server with rate limiting |
| 30 | `khatasnap_ocr/orchestrator.py` | Python | Copy of main orchestrator.py |
| 31 | `khatasnap_ocr/router.py` | Python | Smart doc router (invoice vs list) |
| 32 | `khatasnap_ocr/requirements.txt` | Text | FastAPI, PaddleOCR, EasyOCR, torch |
| 33 | `khatasnap_ocr/pipeline/` | Python | Duplicate of main pipeline (8 files) |
| 34 | `khatasnap_ocr/templates/index.html` | HTML | OCR upload UI |

### Shared Frontend: `khatasnap (5)/khatasnap (2)/khatasnap/`

#### Backend (Express):

| # | Path | Language | Description |
|---|------|----------|-------------|
| 35 | `backend/server.js` | JS | Express server on port 5000 |
| 36 | `backend/.env` | Config | Supabase URL, Gemini API key |
| 37 | `backend/config/database.js` | JS | Supabase client init |
| 38 | `backend/routes/transactions.js` | JS | Voice + transaction CRUD → Supabase |
| 39 | `backend/routes/products.js` | JS | Product CRUD from local JSON |
| 40 | `backend/routes/ocr.js` | JS | OCR text processing → Supabase |
| 41 | `backend/services/gemini.js` | JS | Voice parser (827 lines, pattern-based, NOT Gemini API) |
| 42 | `backend/services/fuzzy-matcher.js` | JS | OCR fuzzy matching |
| 43 | `backend/services/ocr-processor.js` | JS | Receipt text parser |
| 44 | `backend/data/products.json` | JSON | 100 products |
| 45 | `backend/package.json` | JSON | Express, Supabase, Gemini AI, cors |

#### Frontend (React/Vite):

| # | Path | Language | Description |
|---|------|----------|-------------|
| 46 | `frontend/src/App.jsx` | JSX | Main app — 3 tabs |
| 47 | `frontend/src/services/api.js` | JS | API client → localhost:5000 |
| 48 | `frontend/src/services/nicknames.js` | JS | localStorage nickname engine |
| 49 | `frontend/src/components/raj/Calculator.jsx` | JSX | Basic calculator |
| 50 | `frontend/src/components/raj/CalculatorWithVoice.jsx` | JSX | Calculator + voice |
| 51 | `frontend/src/components/raj/InputTabs.jsx` | JSX | Tab switching |
| 52 | `frontend/src/components/raj/ProductList.jsx` | JSX | Product inventory list |
| 53 | `frontend/src/components/shashwat/VoiceInput.jsx` | JSX | Voice billing (29KB) |
| 54 | `frontend/src/components/shashwat/OCRScanner.jsx` | JSX | OCR via Tesseract.js |
| 55 | `frontend/src/components/shashwat/ConfidenceVisualization.jsx` | JSX | Confidence display |
| 56 | `frontend/src/components/shashwat/MismatchDetector.jsx` | JSX | Mismatch UI |
| 57 | `frontend/src/components/tina/DailySummary.jsx` | JSX | Analytics dashboard |
| 58 | `frontend/src/components/tina/ReconciliationPanel.jsx` | JSX | Reconciliation UI |
| 59 | `frontend/vite.config.js` | JS | Port 3000, proxy → 5000 |
| 60 | `frontend/package.json` | JSON | React, Vite, Tailwind, Tesseract.js |

### Other/Duplicate/Legacy:

| # | Path | Description |
|---|------|-------------|
| 61 | `khatasnap (5)/khatasnap_integrated.html` | 110KB monolithic HTML |
| 62 | `khatasnap (5)/khatasnap_mobile_final6.html` | 111KB mobile PWA |
| 63 | `khatasnap (5)/khatasnap_ocr/` | Third copy of OCR module |
| 64 | `khatasnap (5)/udhar/` | Customer credit management |
| 65 | `Khatasnap/templates/index.html` | 131KB Flask-served mobile PWA |

---

## 2. Module Entry Points

| Module | Owner | Entry Point | Framework | Port |
|--------|-------|-------------|-----------|------|
| Main App (all-in-one) | Suryaansh | `Khatasnap/app.py` | Flask | **8000** |
| Standalone OCR | Suryaansh | `khatasnap_ocr/main.py` | FastAPI | **8000** (CONFLICT!) |
| SRE + Inventory | Rizvan | `SRE_upgraded/app.py` | Flask | Unknown |
| Shared Backend | Shashwat/Rizvan | `backend/server.js` | Express | **5000** |
| Shared Frontend | All | `frontend/` | Vite+React | **3000** |
| Mobile PWA | Suryaansh | `templates/index.html` | Raw HTML | served by Flask 8000 |

---

## 3. Inter-Module Data Boundaries

### Voice → Express (React frontend path)
- **Input**: `{ transcript: string }`
- **Output**: `{ items: [{product_name, product_id, price, quantity, confidence}], payment_mode, total_confidence }`

### Voice → Flask (Mobile PWA path)
- **Input**: `{ name, qty }` or `{ items: [{name, qty}] }`
- **Output**: Routes through `/api/bills` with different schema

### OCR Image → Flask Pipeline
- **Input**: `multipart/form-data` image
- **Output**: `{ vendor_name, gstin, invoice_no, items: [{name, hsn, qty, unit, rate, amount}], total, confidence }`

### OCR Text → Express (React path)
- **Input**: `{ extracted_text: string }` (from Tesseract.js in-browser)
- **Output**: `{ items: [{product_name, quantity, price, confidence, matched_from_db}] }`

### SRE Flow (Flask only)
- **Input**: `{ mismatch_amount: number }`
- **Output**: `{ session_id, combos, probabilities, question }`

### Bill Checkout (React → Express → Supabase)
- **Input**: `{ items, payment_mode, total_amount, source }`
- **Target**: Supabase PostgreSQL `transactions` table

---

## 4. Hardcoded Ports/Hosts/URLs

| File | Value | Purpose |
|------|-------|---------|
| `app.py:1155` | `port=8000, host='0.0.0.0'` | Flask |
| `khatasnap_ocr/main.py` | port 8000 default | FastAPI |
| `backend/server.js:11` | `PORT=5000` | Express |
| `api.js:3` | `http://localhost:5000/api` | **HARDCODED** |
| `api.js:127` | `http://localhost:5000/health` | **HARDCODED** |
| `vite.config.js:7` | `port: 3000` | Vite |
| `vite.config.js:12` | `target: 'http://localhost:5000'` | Proxy |
| `server.js:14` | `origin: ['http://localhost:3000']` | CORS |
| `SRE_upgraded/.env` | `aws-1-ap-southeast-1.pooler.supabase.com:5432` | Supabase PG |
| `backend/.env:8` | `https://uoyyakvgsztajubmwhie.supabase.co` | Supabase REST |

---

## 5. Frontend → Backend API Calls

### React → Express (port 5000): All routes work ✅
- GET/POST/PUT/DELETE `/api/products/*` ✅
- POST `/api/transactions/voice-process` ✅
- POST `/api/transactions/add` ✅
- GET `/api/transactions/daily-summary` ✅
- POST `/api/ocr/process-text` ✅

### React → Flask (port 8000): NO connection exists ❌
- OCR pipeline: ❌ Not accessible from React
- SRE engine: ❌ Not accessible from React
- Full inventory: ❌ Not accessible from React
- Dashboard/analytics: ❌ Not accessible from React

**THE CORE PROBLEM**: React frontend talks ONLY to Express (5000). All real functionality lives on Flask (8000). Zero connection between them.

---

## 6. Database Operations

### 6A. SQLite (`khatasnap.db`) — Flask
Tables: categories, suppliers, products (full schema), product_aliases, stock_logs, calculator_transactions, value_product_mapping, processed_transactions, completed_bills

### 6B. Supabase PostgreSQL — Express
Tables: products (UUID, name, price, category, stock), transactions (UUID, items JSONB, payment_mode, total_amount)

### 6C. Local JSON (`products.json`) — Express products.js
Schema: `[{id, name, price, category, stock}]` — 100 products

### 6D. Supabase PostgreSQL (direct psycopg2) — SRE_upgraded
Same Supabase project, direct connection

**THREE databases, never synced. Product added via Express ≠ product in Flask.**

---

## 7. All Dependencies

### Python
flask, flask-cors, psycopg2-binary, python-dotenv, fastapi, uvicorn, python-multipart, opencv-python, numpy, Pillow, requests, paddleocr, pdf2image, pdfplumber, scikit-learn, easyocr, torch

### Node.js (Backend)
express@4.18.2, cors@2.8.5, dotenv@16.3.1, @supabase/supabase-js@2.39.0, @google/generative-ai@0.24.1 (unused), nodemon@3.0.2

### Node.js (Frontend)
react@18.2.0, react-dom@18.2.0, react-router-dom@6.21.0 (unused), axios@1.6.2, date-fns@3.0.0, tesseract.js@5.1.1, vite@7.3.1, tailwindcss@3.4.0

---

## 8. Broken Integration Points

### 🔴 8.1 — Database Fragmentation (CRITICAL)
Three databases never sync. Product/transaction data diverges immediately.

### 🔴 8.2 — Frontend → Wrong Backend (CRITICAL)
React frontend calls Express (5000). Real OCR/SRE/inventory lives on Flask (8000). Zero connection.

### 🔴 8.3 — Product Schema Mismatch (CRITICAL)
Express: `{id: "local-001", name, price, category, stock}`
Flask: `{id: 1, name, category_id, sku, purchase_price, selling_price, current_qty, min_stock, ...}`

### 🟠 8.4 — Voice Processing Duplication (HIGH)
Two completely different voice pipelines with different product databases.

### 🟠 8.5 — Port Conflict (HIGH)
FastAPI OCR and Flask both use port 8000. Cannot run simultaneously.

### 🟠 8.6 — No SRE Gatekeeper (HIGH)
No DB write passes through SRE check. All writes are direct.

### 🟡 8.7 — Missing Calculator Route (MEDIUM)
README mentions `/api/calculator` but route doesn't exist in app.py.

### 🟡 8.8 — OCR Scanner Disconnect (MEDIUM)
React uses Tesseract.js (poor). Proper PaddleOCR/GLM pipeline only on Flask.

### 🟡 8.9 — Transaction Schema Mismatch (MEDIUM)
Voice saves `{product_name, product_id, price, quantity}` to Supabase.
Flask bills expect `{name, qty, price, emoji}` in SQLite.

### 🟡 8.10 — Duplicate Files (LOW)
orchestrator.py ×3, pipeline/ ×3, VoiceInput.jsx ×2, sre_engine.py ×2

### 🟡 8.11 — Unused Imports (LOW)
react-router-dom imported but unused. @google/generative-ai imported but unused.

### 🟡 8.12 — Missing Confirmation Status (MEDIUM)
No `confirmation_status` field exists. Express auto-saves voice transactions at ≥70% confidence.

---

## 9. CORS Issues & Silent Failures

| Service | CORS | Issue |
|---------|------|-------|
| Flask | `*` (open) | Fine |
| FastAPI | `*` (open) | Fine |
| Express | `localhost:3000 only` | **Rejects** requests from Flask or any other origin |

### Silent Failures:
1. Supabase down → Express still runs, transactions fail silently
2. `@google/generative-ai` imported but never called
3. PaddleOCR not installed → Flask returns 503 on OCR
4. products.json corrupted → Express returns empty array

---

## 10. Architecture Diagram (Current — Broken)

```
React Frontend (port 3000)
    │ axios → http://localhost:5000/api
    ▼
Express Backend (port 5000) ──── Supabase PostgreSQL + products.json
├─ transactions.js                ├─ transactions
├─ products.js                    ├─ products  
├─ ocr.js (text only)
└─ gemini.js (voice parser)

═══════ NO CONNECTION ═══════

Flask App (port 8000) ──── SQLite (khatasnap.db)
├─ OCR pipeline (PaddleOCR/GLM)
├─ SRE engine (Bayesian)
├─ Full inventory management
├─ Bill management
└─ Dashboard + analytics
    │
    ▼
Mobile PWA (served by Flask)

═══════ NO CONNECTION ═══════

SRE Upgraded (unknown port) ──── Supabase PostgreSQL (direct psycopg2)
FastAPI OCR (port 8000 CONFLICT)
```

---

## Next Steps

Analysis complete. No code written. Awaiting approval to proceed to Phase 2–7.
