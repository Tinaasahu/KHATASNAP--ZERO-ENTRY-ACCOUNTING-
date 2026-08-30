# 🛒 KhataSnap — Zero-Entry Accounting & Intelligent Shopkeeper Assistant

> **KhataSnap** is a smart, zero-entry accounting and inventory management ecosystem designed for retail shopkeepers and kirana stores. It seamlessly unifies **voice-driven transaction buffering**, **real-time calculator item prediction**, **AI-powered OCR bill parsing**, and a **Smart Reconciliation Engine (SRE)** into a single, intuitive interface.

---

## 🌟 Key Features

- **⚡ Real-Time Item Prediction & Smart Calculator**
  - Instant matching of calculator entries to product catalog items.
  - Price pattern learning and historical item lookup.

- **🎙️ Voice-First Passive ASR & Real-Time Transaction Buffer**
  - Hands-free transaction logging supporting **Hinglish/Hindi/English** speech inputs.
  - Real-time confidence scoring (`high`, `medium`, `low`) with automatic or manual confirmation workflows.

- **📸 AI OCR & Document Processing**
  - Multi-stage document pipeline: Quality Check → Image Enhancement → Document Detection → OCR Text Extraction → Layout Analysis.
  - Automated extraction of items, quantities, taxes, and total amounts from paper receipts and supplier invoices.

- **🛡️ Smart Reconciliation Engine (SRE)**
  - Automated anomaly detection, stock validation, and self-healing transaction logs.
  - Prevents negative inventory, duplicate bill creation, and mismatched totals.

- **📊 Shopkeeper Analytics & Inventory Management**
  - Comprehensive dashboard for sales insights, profit margins, low stock alerts, supplier management, and audit logs.

---

## 🏗️ System Architecture

```text
┌──────────────────────────────────────────────────────────────────┐
│  React Frontend (port 3000 — Vite)                               │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  Orchestrator API (port 8000 — FastAPI)                          │
│  ├─ /api/calculator/*     → Real-time Price & Item Engine        │
│  ├─ /api/txn-buffer/*     → Confidence Engine & Buffer           │
│  ├─ /api/ocr/*            → OCR Engine (port 8001)               │
│  ├─ /api/voice/*          → Voice Service (port 8002)            │
│  ├─ /api/sre/*            → SRE Engine (port 8003)              │
│  └─ /api/inventory/*      → Unified SQLite DB                    │
└──┬────────────────┬────────────────┬─────────────────────────────┘
   │                │                │
   ▼                ▼                ▼
┌────────┐   ┌────────────┐   ┌──────────┐
│  OCR   │   │   Voice    │   │   SRE    │
│  8001  │   │   8002     │   │   8003   │
│ FastAPI│   │  Express   │   │ FastAPI  │
└────────┘   └────────────┘   └──────────┘
```

---

## 🚀 Quick Start Guide

### Prerequisites
- **Python**: `3.10` or higher
- **Node.js**: `v18` or higher (`npm`)
- **System**: macOS, Linux, or Windows

### 1️⃣ Clone the Repository
```bash
git clone https://github.com/Tinaasahu/KHATASNAP--ZERO-ENTRY-ACCOUNTING-.git
cd KHATASNAP--ZERO-ENTRY-ACCOUNTING-
```

### 2️⃣ Run the Unified Startup Script

The startup script handles virtual environment creation, Python/Node package installation, database migration, and launches all microservices and frontend concurrently:

- **Linux / macOS**:
  ```bash
  chmod +x start.sh stop.sh
  ./start.sh
  ```

- **Windows**:
  ```cmd
  start.bat
  ```

### 3️⃣ Access the Application
Open your browser and navigate to:
👉 **[http://localhost:3000](http://localhost:3000)**

- **Backend API Docs (Swagger UI)**: [http://localhost:8000/docs](http://localhost:8000/docs)

### 🛑 Stopping Services
To cleanly stop all background services:
```bash
./stop.sh
```

---

## 📁 Repository Structure

```text
.
├── Khatasnap/
│   ├── orchestrator_api.py   # Main API Gateway (FastAPI)
│   ├── confidence_engine.py   # Multi-signal confidence calculation
│   ├── pattern_engine.py      # Item prediction & pattern learning
│   ├── sre_engine.py          # Smart Reconciliation Engine
│   ├── database.py            # SQLite schema initialization
│   ├── migrate.py             # Database seed & migration script
│   ├── pipeline/              # 8-step OCR computer vision pipeline
│   ├── services/              # Express Node.js voice microservice
│   └── frontend/              # Modern React + Vite application
├── start.sh                   # Unix startup script
├── stop.sh                    # Unix stop script
├── start.bat                  # Windows startup script
├── stop.bat                   # Windows stop script
└── README.md                  # Project documentation
```

---

## 🔌 Core API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/api/calculator/predict-item` | `POST` | Predicts product candidate from keypress amounts & text |
| `/api/calculator/resolve-price` | `POST` | Resolves item price and logs learning statistics |
| `/api/txn-buffer/start` | `POST` | Initializes a real-time transaction buffer session |
| `/api/txn-buffer/finalize` | `POST` | Computes confidence score across ASR + Calculator signals |
| `/api/txn-buffer/commit` | `POST` | Commits finalized transaction to inventory and bill history |
| `/api/ocr/upload` | `POST` | Uploads and processes bill image/PDF via 8-step pipeline |
| `/api/inventory` | `GET` | Retrieves full product inventory with stock levels |
| `/api/dashboard/shopkeeper` | `GET` | Fetches sales metrics, revenue analytics, and stock alerts |

---

## 🛡️ License

This project is open-source and available under the **MIT License**.
