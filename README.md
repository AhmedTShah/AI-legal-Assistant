# LegalMind — AI Legal Research Assistant for Pakistani Law

> **LegalMind** is a full-stack, multi-agent AI application designed to assist Pakistani lawyers with legal research. It combines a **Retrieval-Augmented Generation (RAG)** pipeline, a **LangGraph-style agentic orchestration engine**, a scraped court judgment database, a **PostgreSQL + Mem0 memory layer**, and a **React + FastAPI** chat interface with clickable document citations and formal PDF memo generation.

---

## Table of Contents

- [Features](#features)
- [Architecture Overview](#architecture-overview)
- [Project Structure](#project-structure)
- [AI Agent Pipeline](#ai-agent-pipeline)
- [Memory System](#memory-system)
- [Qdrant Vector Database Collections](#qdrant-vector-database-collections)
- [Court Scrapers](#court-scrapers)
- [Setup & Installation](#setup--installation)
- [Running the Application](#running-the-application)
- [Running the Scraper Pipeline](#running-the-scraper-pipeline)
- [Running the Ingestion Pipeline](#running-the-ingestion-pipeline)
- [Statute Pipeline](#statute-pipeline)
- [API Reference](#api-reference)
- [Configuration](#configuration)
- [Dependencies](#dependencies)
- [Adding a New Court Scraper](#adding-a-new-court-scraper)

---

## Features

- 🤖 **Multi-Agent AI Pipeline** — Intent routing, query decomposition, specialist statute & case law retrieval, and final synthesis via Gemini AI.
- ⚖️ **Pakistani Law Coverage** — Covers PPC, CrPC, PECA 2016, Constitution, and court judgments from SCP, IHC, LHC, BHC, SHC, and PHC.
- 🧠 **Three-Tier Memory System** — Short-term conversation memory, progressive session summarization, and persistent long-term memory via Mem0 + PostgreSQL pgvector.
- 🔗 **Clickable Document Citations** — Every cited case law and statute links directly to a hosted PDF endpoint (`/api/downloads`), enabling one-click access to the full judgment.
- 📄 **Formal Legal Memo PDF Generation** — Generates a professionally structured legal memorandum (Executive Summary → Legal Analysis → Conclusion) downloadable as a PDF.
- 💬 **Conversational Chat UI** — React-based interface with markdown rendering, bold text, bullet lists, and clickable citation links.
- 🌐 **Web Search Fallback** — External queries are automatically routed to a web search agent instead of the RAG pipeline.
- 🧩 **Automatic Filter Relaxation** — If strict Qdrant filters return no results, the Case Law Agent automatically retries with pure vector similarity search.
- 📚 **Multi-Source Statute Serving** — Both court judgment PDFs (`/api/downloads`) and statute PDFs (`/api/statutes`) are served as static file endpoints.

---

## Architecture Overview

```
User (Browser)
     |
     | HTTP (React Vite Frontend)
     v
+---------------------------------------------+
|              FastAPI Backend                 |
|              main.py (:8000)                 |
|                                              |
|  POST /api/chat           (query + session)  |
|  GET  /api/chat/{id}      (history)          |
|  POST /api/generate_pdf   (formal memo)      |
|  GET  /api/downloads/{f}  (case law PDFs)    |
|  GET  /api/statutes/{f}   (statute PDFs)     |
+-----+-----------------------------------+----+
      |                                   |
      | LegalMind Agentic Graph           | PostgreSQL + Mem0
      v                                   v
+---------------------------------------------+    +----------------------------+
|            Agentic Pipeline (graph.py)       |    |   database/memory.py        |
|                                              |    |                            |
| [intent_router]                              |    | - save_message()           |
|      |                                       |    | - get_recent_messages()    |
|      +--EXTERNAL--> [web_search] --> END     |    | - update_session_summary() |
|      |                                       |    | - add_long_term_memory()   |
|      +--INTERNAL--> [query_decomposer]       |    | - search_long_term_memory()|
|                           |                  |    +----------------------------+
|                           v                  |
|                    [statute_agent]            |
|                           |                  |
|                           v                  |
|                   [case_law_agent]            |
|                           |                  |
|                           v                  |
|                  [synthesis_agent] --> Response / PDF
+---------------------------------------------+
      |
      v
+-------------------------------+
|   Qdrant Cloud Vector DB      |
|  - statutes (Layer 1)         |
|  - precedents_db (Layer 2)    |
|  - user_misl_db (Layer 3)     |
+-------------------------------+
```

---

## Project Structure

```
LegalMind/
|
+-- main.py                     # FastAPI entry point: all API routes
+-- config.py                   # Shared constants: models, vector sizes, collection names
+-- requirements.txt            # Python dependencies
|
+-- agents/                     # LangGraph-style AI Agent Nodes
|   +-- graph.py                # Pipeline orchestration (StateGraph engine)
|   +-- state.py                # Shared LegalMindState TypedDict
|   +-- intent_router.py        # Node 1: Classifies query as INTERNAL or EXTERNAL
|   +-- query_decomposer.py     # Node 2: Breaks query into sub-queries with Qdrant filters
|   +-- statute_agent.py        # Node 3: RAG retrieval against statutes collection
|   +-- case_law_agent.py       # Node 4: RAG retrieval against precedents_db collection
|   +-- synthesis_agent.py      # Node 5: Final answer synthesis + PDF memo generation
|   +-- web_search_agent.py     # External Node: Web search fallback for EXTERNAL queries
|   +-- schemas.py              # Pydantic models for structured agent outputs
|
+-- database/                   # Memory & Persistence Layer
|   +-- memory.py               # PostgreSQL + Mem0 memory functions:
|                               #   - Short-term: conversation history per session
|                               #   - Mid-term: progressive session summarization (Gemini)
|                               #   - Long-term: Mem0 pgvector semantic fact storage
|
+-- pipeline/                   # Database Ingestion Pipeline
|   +-- qdrant_client.py        # Qdrant connection + collection bootstrapping
|   +-- ingest_precedents.py    # PDF -> text -> embed -> upsert into precedents_db
|   +-- ingest_misl.py          # User docs -> upsert into user_misl_db
|
+-- scraper/                    # Court Judgment Web Scrapers
|   +-- base_scraper.py         # Shared Playwright async base class
|   +-- run_all.py              # Concurrent runner for all court scrapers
|   +-- courts/
|   |   +-- lhc.py              # Lahore High Court
|   |   +-- ihc.py              # Islamabad High Court (ASMX API)
|   |   +-- scp.py              # Supreme Court of Pakistan
|   |   +-- bhc.py              # Balochistan High Court
|   |   +-- phc.py              # Peshawar High Court
|   |   +-- shc.py              # Sindh High Court
|   +-- utils/
|       +-- pdf_extractor.py    # pdfplumber + EasyOCR fallback for scanned PDFs
|       +-- chunker.py          # Token-aware sliding-window chunker (tiktoken)
|       +-- embedder.py         # Gemini embedding generation with multi-key rotation
|
+-- Statutes_pipeline/          # Layer 1: Statutory Law Ingestion
|   +-- scraper.py              # Statute text scraper (Pakistani law portals)
|   +-- qdrant_ingest.py        # Statute chunks -> statutes Qdrant collection
|   +-- run_pipeline.py         # Entry point for statute ingestion
|   +-- create_statute_coll.py  # Bootstrap statutes Qdrant collection
|   +-- Ammendments_scrapers/   # Scrapers for legislative amendments
|
+-- run_lhc.py                  # Standalone LHC scraper + ingest runner
+-- run_ihc.py                  # Standalone IHC scraper + ingest runner
+-- run_phc.py                  # Standalone PHC scraper + ingest runner
+-- run_scp.py                  # Standalone SCP scraper + ingest runner
+-- run_bhc.py                  # Standalone BHC scraper + ingest runner
|
+-- Frontend/                   # React + TypeScript + Vite Frontend
|   +-- src/
|   |   +-- App.tsx             # Root: chat state, API calls, PDF preview pane
|   |   +-- components/
|   |   |   +-- Sidebar.tsx         # Chat session list and navigation
|   |   |   +-- ChatArea.tsx        # Header, messages, Generate Memo button
|   |   |   +-- ChatInput.tsx       # Message input bar
|   |   |   +-- MessageBubble.tsx   # Markdown parser: bold, bullets, clickable links
|   |   |   +-- MessageBubble.css
|   |   |   +-- ChatArea.css
|   |   |   +-- ChatInput.css
|   |   |   +-- Sidebar.css
|   |   +-- index.css           # Global CSS design tokens
|   |   +-- main.tsx            # React entry point
|   +-- package.json
|   +-- vite.config.ts
|
+-- downloads/                  # Scraped court judgment PDFs (served via /api/downloads)
+-- uploads/                    # Temp user-uploaded documents
+-- .env                        # Environment variables (never commit)
```

---

## AI Agent Pipeline

### Node 1 — Intent Router (`intent_router.py`)
Classifies every incoming query as:
- **`INTERNAL`** — Legal question answered from the RAG pipeline (statutes + case laws).
- **`EXTERNAL`** — Request for a portal link or general web search; bypasses RAG.

### Node 2 — Query Decomposer (`query_decomposer.py`)
Breaks the query into 1–3 focused sub-queries, each with:
- Target agent assignment (`statute_agent` or `case_law_agent`)
- Qdrant metadata filters (court, year range, laws cited, case type)
- Complexity score and primary legal issue detection
- Urdu/English language detection

### Node 3 — Statute Agent (`statute_agent.py`)
- Embeds sub-queries using the Gemini embedding model.
- Queries the `statutes` Qdrant collection with jurisdiction and section-level filters.
- Returns grounded, section-cited statutory answers.

### Node 4 — Case Law Agent (`case_law_agent.py`)
- Queries `precedents_db` with strict metadata filters (court, year, laws cited).
- **Automatically relaxes filters** to pure vector similarity if strict search returns zero results.
- Returns scored, ranked judgment chunks with court, file, and URL metadata.

### Node 5 — Synthesis Agent (`synthesis_agent.py`)
- Aggregates all retrieved context (statutes + case laws).
- Generates a conversational answer with clickable markdown citation hyperlinks.
- For "Generate Memo" requests: produces a full formal memorandum (Executive Summary → Legal Analysis → Conclusion) saved as a PDF via `markdown-pdf`.

---

## Memory System

The memory system (`database/memory.py`) operates in three tiers:

| Tier | Storage | Function |
|---|---|---|
| **Short-term** | PostgreSQL `conversations` table | Stores last N messages per session |
| **Mid-term** | PostgreSQL `conversations.summary` column | Progressive summarization via Gemini when message count > 10 |
| **Long-term** | PostgreSQL pgvector via Mem0 | Lawyer-level semantic fact extraction and retrieval across sessions |

Each API call to `/api/chat`:
1. Saves the lawyer's message to short-term memory.
2. Retrieves relevant long-term facts from Mem0.
3. Assembles a full prompt with LTM facts + session summary + recent messages.
4. After responding, triggers progressive summarization and Mem0 memory updates in the background.

---

## Qdrant Vector Database Collections

| Collection | Layer | Description |
|---|---|---|
| `statutes` | 1 | Pakistani statutory laws: PPC, CrPC, PECA, Constitution, etc. |
| `precedents_db` | 2 | Supreme Court + High Court judgment chunks |
| `user_misl_db` | 3 | User-uploaded case documents: FIRs, witness statements, depositions |

- **Embedding Model:** `models/gemini-embedding-001`
- **Vector Size:** `768` dimensions
- **Distance Metric:** Cosine

---

## Court Scrapers

| File | Court | Scraping Method |
|---|---|---|
| `lhc.py` | Lahore High Court | Playwright browser automation |
| `ihc.py` | Islamabad High Court | ASMX WebService API (`mis.ihc.gov.pk`) |
| `scp.py` | Supreme Court of Pakistan | Playwright browser automation |
| `bhc.py` | Balochistan High Court | Playwright browser automation |
| `phc.py` | Peshawar High Court | Playwright browser automation |
| `shc.py` | Sindh High Court | Playwright browser automation |

---

## Setup & Installation

### 1. Clone the repository

```bash
git clone https://github.com/AhmedTShah/AI-legal-Assistant.git
cd AI-legal-Assistant
```

### 2. Create a Python virtual environment

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/macOS
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
# Gemini API Keys (comma-separated for multi-key rotation)
GEMINI_API_KEY=your_primary_key_here
GEMINI_API_KEYS=key1,key2,key3,key4

# Qdrant Cloud
QDRANT_URL=https://your-cluster-id.eu-central-1-0.aws.cloud.qdrant.io:6333
QDRANT_API_KEY=your_qdrant_api_key

# PostgreSQL (for memory layer)
DATABASE_URL=postgresql://user:password@host:5432/legalmind

# Mem0 (for long-term memory)
MEM0_API_KEY=your_mem0_api_key
```

### 5. Install Frontend dependencies

```bash
cd Frontend
npm install
```

---

## Running the Application

### Start the FastAPI Backend

```bash
# From the project root
venv\Scripts\uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Backend available at: `http://127.0.0.1:8000`
API docs (auto-generated): `http://127.0.0.1:8000/docs`

### Start the React Frontend

```bash
cd Frontend
npm run dev
```

Frontend available at: `http://localhost:5173`

---

## Running the Scraper Pipeline

### Run all scrapers at once

```bash
python -m scraper.run_all --keyword "criminal" --year 2024
```

### Run individual court scrapers

```bash
python run_ihc.py    # Islamabad High Court
python run_lhc.py    # Lahore High Court
python run_scp.py    # Supreme Court of Pakistan
python run_phc.py    # Peshawar High Court
python run_bhc.py    # Balochistan High Court
```

Scraped PDFs are saved to `downloads/` and automatically served at:
`http://localhost:8000/api/downloads/{filename}`

---

## Running the Ingestion Pipeline

### Ingest court judgments into `precedents_db`

```bash
# Single PDF
python -m pipeline.ingest_precedents \
    --pdf downloads/judgment_2024.pdf \
    --court IHC --year 2024 \
    --laws-cited "PPC,CrPC" --case-type criminal

# Batch ingest entire downloads folder
python -m pipeline.ingest_precedents --dir downloads/ --court IHC
```

### Ingest user documents into `user_misl_db`

```bash
python -m pipeline.ingest_misl \
    --file uploads/fir_001.pdf \
    --doc-type FIR \
    --case-number "123/2024" \
    --uploaded-by "advocate@firm.com"
```

---

## Statute Pipeline

Layer 1 (statutory laws) is managed via `Statutes_pipeline/`:

```bash
cd Statutes_pipeline
python run_pipeline.py
```

This scrapes statutory law text from Pakistani law portals and ingests it into the `statutes` Qdrant collection.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/api/chat` | Submit a legal query (with session_id, user_id) |
| `GET` | `/api/chat/{session_id}` | Retrieve conversation history for a session |
| `POST` | `/api/generate_pdf` | Generate a formal legal memo as a downloadable PDF |
| `GET` | `/api/downloads/{filename}` | Serve a scraped court judgment PDF |
| `GET` | `/api/statutes/{filename}` | Serve a statute PDF |

### POST /api/chat — Request Body
```json
{
  "message": "What is the punishment under Section 302 PPC?",
  "session_id": "session-abc123",
  "user_id": "lawyer_123"
}
```

### POST /api/chat — Response
```json
{
  "response": "Under Section 302 PPC...",
  "intent": "INTERNAL",
  "detected_language": "English",
  "primary_legal_issue": "Qatl-i-Amd",
  "citations": [],
  "retrieved_chunks": [...]
}
```

---

## Configuration

All shared constants are in `config.py`:

| Constant | Default Value | Description |
|---|---|---|
| `CHAT_MODEL` | `gemini-3.1-flash-lite` | Gemini model for text generation |
| `EMBEDDING_MODEL` | `models/gemini-embedding-001` | Gemini model for embeddings |
| `VECTOR_SIZE` | `768` | Embedding vector dimensions |
| `STATUTES_COLLECTION` | `statutes` | Layer 1 Qdrant collection name |
| `PRECEDENTS_COLLECTION` | `precedents_db` | Layer 2 Qdrant collection name |
| `MISL_COLLECTION` | `user_misl_db` | Layer 3 Qdrant collection name |
| `MAX_CHUNK_SIZE` | `1500` | Max characters per text chunk |
| `BATCH_SIZE` | `50` | Batch size for Qdrant upserts |

---

## Dependencies

| Package | Purpose |
|---|---|
| `fastapi` | REST API server |
| `uvicorn` | ASGI server |
| `google-generativeai` | Gemini AI for embeddings and text generation |
| `qdrant-client` | Qdrant vector database client |
| `playwright` | Async browser automation for court scrapers |
| `pdfplumber` | PDF text extraction |
| `easyocr` | OCR fallback for scanned/image-based PDFs |
| `tiktoken` | Token-accurate text chunking |
| `httpx` | HTTP client for PDF downloads |
| `markdown-pdf` | Converts Markdown legal memos to PDF |
| `python-dotenv` | Environment variable management |
| `pydantic` | Data validation and API schemas |
| `psycopg2` | PostgreSQL client for memory layer |
| `mem0ai` | Long-term semantic memory via pgvector |

---

## Adding a New Court Scraper

1. Create `scraper/courts/<court_code>.py`
2. Subclass `BaseScraper` from `scraper/base_scraper.py`
3. Implement the required abstract methods:
   - `search_url` (property) — target court portal URL
   - `submit_search(page, keyword)` — fills and submits the search form
   - `extract_pdf_links(page)` — scrapes all PDF download URLs from results
   - `go_to_next_page(page)` — returns `True` if pagination succeeded
4. Register it in `scraper/run_all.py`
5. Create a `run_<court>.py` standalone runner in the project root
