# Contract Note Parser & Financial Web Platform 📊🚀

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![Status](https://img.shields.io/badge/Status-Production%20Ready-success.svg)]()
[![Web API](https://img.shields.io/badge/Web%20API-RESTful%20JSON-orange.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **Developer:** Arham Begani  
> **GitHub Repository:** [https://github.com/Arham-1313/file_parser](https://github.com/Arham-1313/file_parser)  
> **Live Website Link:** [https://file-parser-r7b0.onrender.com](https://file-parser-r7b0.onrender.com) *(or configure via `python server_manager.py set-url`)*  
> **Interactive API Docs:** `http://localhost:5000/api/docs`

---

## 📌 Project Overview

**Contract Note Parser** is a broker-template-driven web application and RESTful API designed to parse Indian stock market **Equity Segment Contract Notes** (PDF format).

Contract notes often present intricate formatting quirks across different stockbrokers. This platform solves the critical fintech problem of **spatial address confusion, corporate vs client PAN collisions, and inconsistent tabular structures**, extracting standardized financial records into normalized JSON outputs.

Built with an **all-in-one Server Management Controller (`server_manager.py`)**, an interactive responsive web interface, and full REST API compliance.

---

## 🌟 Key Features

### 1. 🏢 Multi-Broker Template Engine
- **Zerodha Broking Limited** (`zerodha`): Optimized spatial parser for Zerodha notes.
- **Shoonya / Finvasia Securities** (`shoonya`): Precision parser for Shoonya digital contract notes.
- **Systematix Shares & Stocks** (`systematix`): Coordinate-zone parser for Systematix equity records.
- **Universal / Generic SEBI Broker** (`generic`): Fallback engine complying with standard SEBI contract note layouts.
- **Auto-Detection (`auto`)**: Automatically analyzes header CIN, SEBI Registration ID, and table layout to select the optimal broker template.

### 2. 🛡️ Anti-Confusion Guarantee (Strict Spatial Boundary Isolation)
- **Registered Office vs Client Address Isolation**: Broker corporate address is strictly parsed from the header zone; client address is isolated within the designated recipient box.
- **Null Safety**: If the client address is missing in the document, it returns `null`—**never** misattributing the broker's corporate headquarters as the client's home address.
- **PAN Disambiguation**: Cross-validates corporate broker PAN against client PAN to eliminate data leakage.

### 3. 🌐 Modern Web Interface & REST API
- **Interactive Web App**: Upload PDF contract notes directly from the browser, preview parsed parties and transaction breakdown, view trade analytics, and export JSON/CSV data.
- **Interactive API Documentation**: Full OpenAPI 3.0 specification available at `/api/docs`.
- **Health Check Endpoint**: Real-time heartbeat probe at `/api/health`.

### 4. 🎛️ All-in-One Server Management Controller (`server_manager.py`)
- Single command server lifecycle management: **Start**, **Stop**, **Restart**, and **Status**.
- Automatic port conflict detection, background process tracking, and graceful shutdown.
- Configurable **Live Website Link** and **GitHub Link** displayed right in the status dashboard.
- Built-in instant public web tunnel helper (`cloudflared`, `ngrok`, `localtunnel`).

---

## 🛠️ Technology Stack

| Layer | Technologies |
|---|---|
| **Backend Engine** | Python 3.11+ / 3.14, `pdfplumber`, `reportlab`, `sqlite3` |
| **Web Server** | Native Python `http.server.HTTPServer` (Zero external framework bloat) |
| **API Architecture** | RESTful JSON, CORS enabled, OpenAPI 3.0 specs |
| **Frontend** | Vanilla JavaScript (ES6+), HTML5 semantic structure, Glassmorphism CSS |
| **DevOps & Management** | `server_manager.py` (CLI & Interactive), `Procfile`, `render.yaml` |

---

## 🚀 Quickstart Guide

### 1. Clone the Repository
```bash
git clone https://github.com/Arham-1313/file_parser.git
cd file_parser
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Start the Web Server
You can launch the server using the **Server Management Controller**:
```bash
python server_manager.py start
```
*Or run interactively:*
```bash
python server_manager.py
```

The web application will be live at: **`http://localhost:5000`**

---

## 🎛️ Server Management Controller (`server_manager.py`)

The included `server_manager.py` script provides unified server management for local development, production hosting, and portfolio demonstration:

| Command | Description |
|---|---|
| `python server_manager.py start` | Starts the web server in the background and verifies health |
| `python server_manager.py stop` | Gracefully terminates server and frees port 5000 |
| `python server_manager.py restart` | Cleanly stops and restarts the server |
| `python server_manager.py status` | Displays full server dashboard (Uptime, PID, Port, Local URL, Live Website Link) |
| `python server_manager.py set-url <url>` | Sets your live deployment website link (persists in `config.json`) |
| `python server_manager.py url` | Prints all accessible links (Local, Network LAN, Live Website) |
| `python server_manager.py open` | Opens the web application directly in your default browser |
| `python server_manager.py logs` | Displays the last 30 lines of `server.log` |
| `python server_manager.py tunnel` | Generates a free instant public HTTPS link (`cloudflared` / `ngrok` / `localtunnel`) |
| `python server_manager.py` | Launches the interactive visual console menu |

### 📊 Server Status Dashboard Preview
```text
================================================================
  CONTRACT NOTE PARSER - SERVER STATUS DASHBOARD
  Developer: Arham Begani | Personal Open Source Project
================================================================
  Status        : [ONLINE - RUNNING] [HEALTHY (18.2 ms)]
  Process ID    : 12345
  Port Bound    : 5000
  Server Uptime : 0:14:22

  Accessible URLs:
  * Local Web App       : http://localhost:5000
  * Local Network (LAN) : http://192.168.1.5:5000
  * Interactive API Docs: http://localhost:5000/api/docs
  * Live Website Link   : https://file-parser-r7b0.onrender.com
  * GitHub Repository   : https://github.com/Arham-1313/file_parser
================================================================
```

---

## 📡 REST API Reference

### 1. Parse Contract Note
- **Endpoint:** `POST /api/parse`
- **Content-Type:** `application/json`
- **Payload:**
```json
{
  "file_base64": "<base64_encoded_pdf>",
  "file_name": "contract_note.pdf",
  "password": null,
  "template": "auto"
}
```
- **Response:**
```json
{
  "template_info": {
    "template_id": "zerodha",
    "template_name": "Zerodha Broking Limited",
    "confidence": 1.0
  },
  "client_details": {
    "name": "ARIHANT BEGANI",
    "client_id": "DA9605",
    "pan": "ABCDE1234F",
    "address": null
  },
  "broker_details": {
    "name": "ZERODHA BROKING LTD.",
    "sebi_registration_no": "INZ000031633",
    "cin": "U67120KA2010PLC055555",
    "gstin": "29AABCZ2123C1Z6",
    "pan": "AABCZ2123C"
  },
  "transactions": [
    {
      "security_name": "TATAELXSI",
      "isin": "INE670A01012",
      "transaction_type": "SELL",
      "quantity": 6,
      "purchase_price_per_share": 3685.0,
      "brokerage": 0.0
    }
  ]
}
```

### 2. Supported Broker Templates
- **Endpoint:** `GET /api/templates`
- Returns all registered broker template specifications and spatial profiles.

### 3. Server Health Probe
- **Endpoint:** `GET /api/health`
- Returns service status, latency, and uptime.

---

## 📁 Project Structure

```text
file_parser/
├── contract_note_parser.py   # Core extraction engine and spatial parser
├── app.py                    # Web server, HTTP handlers, and REST API
├── server_manager.py         # All-in-one Server Management Controller
├── broker_templates.py       # Broker spatial definitions (Zerodha, Shoonya, Systematix)
├── zone_manager.py           # SQLite spatial coordinate manager
├── requirements.txt          # Python dependencies
├── Procfile                  # Cloud deployment process file
├── render.yaml               # Render infrastructure-as-code deployment
├── templates/
│   ├── index.html            # Responsive web UI interface
│   └── api_docs.html         # Interactive OpenAPI 3.0 documentation
├── sample_files/             # Sample Indian equity contract notes
└── README.md                 # Complete documentation
```

---

## 👨‍💻 Author & License

- **Developer:** Arham Begani
- **License:** [MIT License](LICENSE)
