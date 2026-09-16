# 🚀 Production Text-to-SQL Gateway: Deployment & Configuration Guide

This guide details environment-variable configuration, canonical alias resolution, single-file threshold management, 100% self-hosted zero-paid API verification, plugin widget cross-server deployment, and manual fine-tuning CLI execution.

---

## 1. Environment Variable Configuration

All network endpoints, database strings, Redis caching parameters, and paths are environment-driven via `.env` or system environment variables. No `localhost` or local file paths are hardcoded in application logic.

Create or update your `.env` file in `backend/.env`:

```env
# Server Network Configuration
PORT=8001
HOST=0.0.0.0

# Local LLM Serving (Ollama Self-Hosted)
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=sqlcoder:15b
OLLAMA_RESPONSE_MODEL=qwen2.5-coder:7b

# Database Connection (SQLAlchemy format - MS SQL Server, SQLite, PostgreSQL)
DB_CONNECTION_STRING=sqlite:///backend/app/db.json
# Example MS SQL Server: mssql+pyodbc://sa:YourPassword@192.168.1.10/OmniDash_CMS?driver=ODBC+Driver+17+for+SQL+Server

# Redis Configuration (Optional Fast Read-Through / Write-Through Cache)
REDIS_ENABLED=true
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

# Pipeline Confidence & Resolution Thresholds
SYMSPELL_MAX_EDIT_DISTANCE=2
FOLLOWUP_EMBEDDING_SIMILARITY_THRESHOLD=0.72
VALUE_RESOLVER_FUZZY_THRESHOLD=82.0
VALUE_RESOLVER_PHONETIC_THRESHOLD=80.0
VALUE_RESOLVER_EMBEDDING_THRESHOLD=0.75
SCHEMA_LINKER_SIMILARITY_THRESHOLD=0.35
CONFIDENCE_ABSTENTION_THRESHOLD=0.65

# Data-Collection Safeguard (Minimum dataset size before manual fine-tuning export)
MIN_FINETUNING_EXAMPLES=300
```

---

## 2. Canonical Alias Table Conflict Resolution Architecture

The system resolves entity spelling variants, abbreviations, and nicknames using a 5-step cascade.

```
                          ┌───────────────────────────┐
                          │   Local JSON File         │
                          │   (Canonical Source of    │
                          │    Truth on Disk)         │
                          │   backend/app/data/       │
                          │   alias_table.json        │
                          └─────────────┬─────────────┘
                                        │
                         Init Sync / Write-Through
                                        │
                                        ▼
                          ┌───────────────────────────┐
                          │   Redis Cache / Memory    │
                          │   (Fast Read-Through)     │
                          └───────────────────────────┘
```

### Source of Truth Guarantee
- **Disk file `backend/app/data/alias_table.json` is the CANONICAL SOURCE OF TRUTH.**
- **Redis is strictly a read-through / write-through cache.**
- On backend startup, `ValueResolver` loads canonical mappings from `alias_table.json`.
- If Redis is configured and reachable, it populates Redis cache from `alias_table.json`.
- When an analyst or user submits a confirmed value correction (via the 👍/👎 feedback endpoint), the backend **writes immediately to `alias_table.json` on disk** and updates Redis.
- If Redis goes offline or restarts, no mapping is lost — the system seamlessly re-reads `alias_table.json`.

---

## 3. Centralized Thresholds & Configuration (`backend/app/config.py`)

All numerical thresholds (fuzzy match %, phonetic threshold, abstention cutoff, vector similarity cutoffs, retry max counts) are housed in `backend/app/config.py` driven by `.env`. You can tune these after observing real results without altering code.

---

## 4. 100% Free / Open-Source / Self-Hosted Guarantee

The entire system relies exclusively on free, open-source, self-hosted tools. **Zero paid APIs** (e.g. OpenAI, Anthropic, Cohere) are used anywhere in the pipeline:

| Function | Open-Source Technology | License |
|---|---|---|
| Spell Normalization | `symspellpy` | MIT |
| Fuzzy Matching | `rapidfuzz` | MIT |
| Phonetic Matching | `jellyfish` | BSD-2-Clause |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`) | Apache 2.0 |
| Schema Graph | `networkx` | BSD-3-Clause |
| AST Validation | `sqlglot` | MIT |
| LLM Serving | Ollama (`sqlcoder:15b`, `qwen2.5-coder`) | MIT / Apache 2.0 |
| Caching | Redis / Python in-memory dict | BSD / MIT |

---

## 5. Plugin Widget Deployment & Cross-Server Rebuilding

The embeddable plugin widget (`widget.js` & `widget.css`) supports dynamic, runtime-configured backend API base URLs. The same compiled bundle can point to any backend deployment server.

### Option A: Embed via Script Tag
Embed this HTML snippet on any external bank portal or intranet server:

```html
<script 
  src="http://YOUR-BACKEND-SERVER-IP:8000/plugin/widget.js"
  data-sbi-cms-gateway="http://YOUR-BACKEND-SERVER-IP:8000"
  data-auto-open="false"
  data-theme="dark"
  data-position="bottom-right">
</script>
```

### Option B: Programmatic Initialization
```javascript
window.initSbiCmsWidget({
  gatewayUrl: 'http://YOUR-BACKEND-SERVER-IP:8000',
  theme: 'dark',
  position: 'bottom-right'
});
```

### Rebuilding Plugin Bundle when Source Code Changes
If you modify widget React components in `frontend/src/`:
1. Open a terminal in the `frontend/` directory:
   ```bash
   cd frontend
   npm run build:plugin
   ```
2. The compiled assets (`widget.js` and `widget.css`) will automatically be output to `backend/plugin_assets/`.
3. Any server pointing to `http://YOUR-BACKEND-SERVER-IP:8000/plugin/widget.js` will immediately receive the updated widget!

---

## 6. Manual Data-Collection & Fine-Tuning Execution Workflow

Fine-tuning is **strictly manually triggered** and will **never** run automatically from the main pipeline.

### Current Phase: Data-Collection
In production, the chatbot logs user queries, confidence scores, and analyst 👍/👎 corrections into `backend/app/data/feedback_dataset.jsonl`.

### Manual Fine-Tuning Dataset Export
When you decide to run a fine-tuning iteration:
```bash
python backend/scripts/prepare_finetuning_dataset.py --min-examples 300
```
- The script checks that `feedback_dataset.jsonl` contains at least `--min-examples` (default 300).
- If below 300 examples, it refuses to run and prompts you to collect more feedback (pass `--force` to bypass for testing).
- Outputs formatted `sft_dataset.jsonl` (Supervised Fine-Tuning) and `dpo_dataset.jsonl` (Direct Preference Optimization) under `backend/app/data/finetuning_export/`.

### Manual Benchmark Evaluation
To evaluate execution accuracy on test queries:
```bash
python backend/scripts/evaluate_pipeline.py
```
Reports execution accuracy %, syntax validity %, and honest abstention rate %.
