# 🏛️ SBI CMS Intelligence — Domain-Specific NL-to-SQL Chatbot Gateway

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://react.dev/)
[![Sentence Transformers](https://img.shields.io/badge/Embeddings-all--MiniLM--L6--v2-FF6F00?style=for-the-badge&logo=huggingface&logoColor=white)](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
[![MS SQL Server](https://img.shields.io/badge/Database-MS_SQL_Server-CC292B?style=for-the-badge&logo=microsoft-sql-server&logoColor=white)](https://www.microsoft.com/en-us/sql-server/)

A domain-specific **Natural Language Processing (NLP) & Machine Learning Text-to-SQL Gateway** built for the State Bank of India Centralized Monitoring System (SBI CMS). It enables operators and bank executives to query alert data, attachments, and metadata using natural language.

**Strictly scoped to SBI CMS alert data:** `vw_AlertReporting`, `AlertsDetails`, `AlertAttachment`, `RawAttachments`, `Jurisdiction_mstr`, `Junction_mstr`, `Sensor_Master`.

---

## 🌟 Key Capabilities

* **Schema-Scoped Querying**: Query only the approved SBI CMS tables for alert data, attachments, and metadata.
* **Semantic Schema Linking (`all-MiniLM-L6-v2`)**: Computes dense vector Cosine Similarity to map user query tokens to target database tables/columns.
* **Categorical Value Grounding**: Automatically grounds natural language terms (e.g. `"nariman point"`) to exact database string literals (e.g. `"SBI Nariman Point"`).
* **Multi-Turn Context Resolution**: Remembers dialogue context across follow-up queries (e.g. *"Show incidents in Bhopal LHO"* → *"Are any of them critical?"*).
* **Deterministic Rule-Based Pipeline**: Primary query engine works without LLM dependency.
* **LLM Enhancement**: Ollama LLM provides reasoning for unseen phrasings (optional enhancement).
* **Attachment Support**: Fetches and displays alert attachments (images/videos) from `RawAttachments` via base64 conversion.
* **100% Shadow DOM Embeddable Plugin**: Includes a lightweight, style-isolated JavaScript floating widget that can be embedded into any external bank web portal or intranet with a single `<script>` tag.

---

## 🏗️ System Architecture

```text
┌────────────────────────────────────────────────────────┐
│   External Bank Portals / Intranet Web Applications    │
│  <script src="http://GATEWAY:8001/plugin/widget.js">   │
└──────────────────────────┬─────────────────────────────┘
                           │ HTTP POST /api/chat (JSON)
                           ▼
┌────────────────────────────────────────────────────────┐
│             Central FastAPI Gateway (8001)             │
│                                                        │
│  ┌────────────────────┐   ┌─────────────────────────┐  │
│  │ SchemaEngine       │   │ SchemaLinker            │  │
│  │ (Schema Introspect │   │ (Vector Similarity &    │  │
│  │  & Embedding Index)│   │  Categorical Grounding) │  │
│  └─────────┬──────────┘   └────────────┬────────────┘  │
│            │                           │               │
│            ▼                           ▼               │
│  ┌──────────────────────────────────────────────────┐  │
│  │ Pipeline Orchestrator (Rule-Based + Optional LLM) │  │
│  └──────────────────────────┬───────────────────────┘  │
│                             │                          │
│                             ▼                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │ SBI CMS Database (vw_AlertReporting, etc.)         │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start (Local Development)

### 1. Clone & Set Up Virtual Environment

```bash
git clone https://github.com/riaatiwarii/NLP-chat-bot-sql.git
cd NLP-chat-bot-sql

# Create Python Virtual Environment
python -m venv backend/.venv

# Activate Virtual Environment (Windows PowerShell)
.\backend\.venv\Scripts\Activate.ps1

# Install Dependencies
pip install -r backend/requirements.txt
npm run install:frontend
```

### 2. Configure Database Credentials

Create a `backend/.env` file (REQUIRED - no fallbacks):

```env
DB_USER=sa
DB_PASSWORD=YourPassword
DB_HOST=198.38.87.117
DB_PORT=1433
DB_NAME=OmniDash_CMS
API_KEY=your_secure_api_key_here
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8001
```

### 3. Run Development Servers

```bash
# Terminal 1: Launch Backend Gateway
npm run backend

# Terminal 2: Launch Frontend App
npm run frontend
```

* **Frontend Application**: `http://localhost:3000/`
* **FastAPI Backend Gateway**: `http://localhost:8001`
* **Plugin Integration Demo**: `http://localhost:8001/plugin/demo.html`

---

## 🔌 Embedding the Chatbot Plugin in External Web Portals

Any existing website, internal dashboard, or intranet portal can embed the AI Chatbot widget by adding a single `<script>` tag:

```html
<!-- SBI CMS Embeddable AI Assistant Plugin -->
<script 
  src="http://<GATEWAY_IP>:8001/plugin/widget.js" 
  data-sbi-cms-gateway="http://<GATEWAY_IP>:8001" 
  data-auto-open="false"
  data-theme="dark"
  data-position="bottom-right">
</script>
```

### Supported `data-*` Configuration Attributes

| Attribute | Options | Default | Description |
|---|---|---|---|
| `data-sbi-cms-gateway` | URL | `""` | Public/Internal IP of the FastAPI Gateway |
| `data-theme` | `dark` \| `light` | `dark` | Visual theme palette |
| `data-position` | `bottom-right` \| `bottom-left` | `bottom-right` | Screen placement position |
| `data-auto-open` | `true` \| `false` | `false` | Automatically opens modal on page load |
| `data-api-key` | Token string | `""` | Optional Bearer authorization token |

### Plugin Host Endpoints & Options

* **Standard Plugin Script (`/plugin/widget.js`)**: Direct `<script>` embed tag for web portals.
* **Transparent iFrame Host (`/plugin/widget_only.html`)**: Transparent HTML host page for CSP-restricted iFrames (shows ONLY the chatbot icon/modal without background portal cards).
* **Demo Portal Page (`/plugin/demo.html`)**: Complete interactive portal integration example.

---

## 📦 Standalone Executable Packaging & Windows Server Launch (`SbiCmsGateway.exe`)

To build and run the central gateway as a 100% portable, standalone Windows application **without requiring Python, PyTorch, or dependencies installed on the server**:

### 1. Build Executable Package
Run the automated builder script:
```cmd
d:\NLP-chat-bot-sql\build_exe.bat
```
This compiles all backend modules, ML models, and plugin assets into `dist\SbiCmsGateway\SbiCmsGateway.exe`.

### 2. Run Server Service
Double-click `start_server.bat` or run:
```cmd
d:\NLP-chat-bot-sql\start_server.bat
```
This automatically opens **Port 8001** in Windows Defender Firewall and starts `SbiCmsGateway.exe`.

---

## 🖥️ 24/7 Unattended Windows Service Deployment

To run the gateway continuously on an On-Premise Windows Server (unattended boot without requiring user login):

1. Copy the project folder to your Windows Server.
2. Open **PowerShell as Administrator** and run:
   ```powershell
   cd D:\NLP-chat-bot-sql
   .\setup_windows_server.ps1
   ```
3. The script automatically registers a Windows Scheduled Task (`SbiCmsGatewayTask`) under `NT AUTHORITY\SYSTEM` and configures the Windows Defender Firewall for Port 8001.

---

## 📖 Further Documentation

* **[TECHNICAL_DOCUMENTATION.md](TECHNICAL_DOCUMENTATION.md)**: Comprehensive deep dive into the vector schema engine, entity grounding algorithm, self-repair loop, and system internals.

---

## 📜 License

Internal Proprietary Code — State Bank of India (Centralized Monitoring System).
