# LegalMind — AI Legal Research Assistant for Pakistani Law

> **LegalMind** is a full-stack, multi-agent AI application designed to assist Pakistani lawyers with legal research. It combines a **Retrieval-Augmented Generation (RAG)** pipeline, a **LangGraph-style agentic orchestration engine**, a scraped court judgment database, and a **React + FastAPI** chat interface with clickable document citations and formal PDF memo generation.

---

## Table of Contents

- [Features](#features)
- [Architecture Overview](#architecture-overview)
- [Project Structure](#project-structure)
- [AI Agent Pipeline](#ai-agent-pipeline)
- [Qdrant Vector Database Collections](#qdrant-vector-database-collections)
- [Court Scrapers](#court-scrapers)
- [Setup & Installation](#setup--installation)
- [Running the Application](#running-the-application)
- [Running the Scraper Pipeline](#running-the-scraper-pipeline)
- [Running the Ingestion Pipeline](#running-the-ingestion-pipeline)
- [Statute Pipeline](#statute-pipeline)
- [Configuration](#configuration)
- [Dependencies](#dependencies)
- [Adding a New Court Scraper](#adding-a-new-court-scraper)

---

## Features

- 🤖 **Multi-Agent AI Pipeline** — Intent routing, query decomposition, specialist statute & case law retrieval, and final synthesis via Gemini AI.
- ⚖️ **Pakistani Law Coverage** — Covers Pakistan Penal Code, CrPC, PECA 2016, and court judgments from SCP, IHC, LHC, BHC, SHC, and PHC.
- 🔗 **Clickable Document Links** — Every cited case law and statute is backed by a locally hosted PDF endpoint (`/api/downloads`), enabling one-click access to the full judgment.
- 📄 **Formal Legal Memo PDF Generation** — Generates a professionally structured legal memorandum (Executive Summary → Legal Analysis → Conclusion) downloadable as a PDF.
- 💬 **Conversational Chat UI** — React-based interface with markdown rendering, inline bold text, bullet lists, and clickable citation links.
- 🌐 **Web Search Fallback** — External queries are automatically routed to a web search agent instead of RAG retrieval.
- 🧠 **Automatic Filter Relaxation** — If strict Qdrant filters return no results, the Case Law Agent automatically retries with vector similarity only.

---

## Architecture Overview

```
User (Browser)
     |
     | HTTPS (React Vite Frontend)
     v
+-------------------------------------+
|         FastAPI Backend             |
|         main.py (:8000)             |
|                                     |
|  POST /api/chat                     |
|  POST /api/generate_pdf             |
|  GET  /api/downloads/{file}  (PDF)  |
+------------------+------------------+
                   | LegalMind Graph
                   v
+-----------------------------------------------------------------+
|                    Agentic Pipeline (graph.py)                   |
|                                                                  |
|  [intent_router] --EXTERNAL--> [web_search] --> END             |
|       |                                                          |
|       +--INTERNAL--> [query_decomposer]                          |
|                            |                                     |
|                            v                                     |
|                     [statute_agent]  ---- Qdrant: statutes       |
|                            |                                     |
|                            v                                     |
|                    [case_law_agent]  ---- Qdrant: precedents_db  |
|                            |                                     |
|                            v                                     |
|                   [synthesis_agent]  --> Final Response / PDF    |
+-----------------------------------------------------------------+
                   |
                   v
+-----------------------------+
|   Qdrant Cloud Vector DB    |
|  - statutes                 |
|  - precedents_db            |
|  - user_misl_db             |
+-----------------------------+
```

---

## Project Structure

```
LegalMind-Layer2/
|
+-- main.py                     # FastAPI app: /api/chat, /api/generate_pdf, /api/downloads
+-- config.py                   # Shared constants: models, vector size, collection names
+-- requirements.txt            # Python dependencies
|
+-- agents/                     # LangGraph-style AI Agents
|   +-- graph.py                # Pipeline orchestration engine (StateGraph)
|   +-- state.py                # Shared LegalMindState TypedDict
|   +-- intent_router.py        # Node 1: Classifies query as INTERNAL or EXTERNAL
|   +-- query_decomposer.py     # Node 2: Breaks query into sub-queries with Qdrant filters
|   +-- statute_agent.py        # Node 3: RAG search against statutes collection
|   +-- case_law_agent.py       # Node 4: RAG search against precedents_db collection
|   +-- synthesis_agent.py      # Node 5: Synthesizes final answer + builds PDF memo
|   +-- web_search_agent.py     # External Node: Web search fallback for EXTERNAL queries
|   +-- schemas.py              # Pydantic models for query decomposition output
|
+-- pipeline/                   # Database Ingestion Pipeline
|   +-- qdrant_client.py        # Qdrant connection + collection bootstrapping
|   +-- ingest_precedents.py    # PDF -> text -> embed -> upsert into precedents_db
|   +-- ingest_misl.py          # User docs -> upsert into user_misl_db
|
+-- scraper/                    # Court Judgment Scrapers
|   +-- base_scraper.py         # Shared Playwright async base class
|   +-- run_all.py              # Runs all court scrapers concurrently
|   +-- courts/
|   |   +-- lhc.py              # Lahore High Court scraper
|   |   +-- ihc.py              # Islamabad High Court scraper (ASMX API)
|   |   +-- scp.py              # Supreme Court of Pakistan scraper
|   |   +-- bhc.py              # Balochistan High Court scraper
|   |   +-- phc.py              # Peshawar High Court scraper
|   |   +-- shc.py              # Sindh High Court scraper
|   +-- utils/
|       +-- pdf_extractor.py    # pdfplumber + EasyOCR fallback for scanned PDFs
|       +-- chunker.py          # Token-aware sliding-window chunker (tiktoken)
|       +-- embedder.py         # Gemini embedding generation with multi-key rotation
|
+-- Statutes_pipeline/          # Separate pipeline for statutory law (Layer 1)
|   +-- scraper.py              # Statute text scraper (Pakistani law websites)
|   +-- qdrant_ingest.py        # Statute chunks -> statutes collection
|   +-- run_pipeline.py         # Entry point for statute ingestion
|   +-- create_statute_coll.py  # Bootstrap statutes Qdrant collection
|
+-- run_lhc.py                  # Standalone LHC scraper + ingest runner
+-- run_ihc.py                  # Standalone IHC scraper + ingest runner
+-- run_phc.py                  # Standalone PHC scraper + ingest runner
+-- run_scp.py                  # Standalone SCP scraper + ingest runner
+-- run_bhc.py                  # Standalone BHC scraper + ingest runner
|
+-- Frontend/                   # React + Vite Frontend
|   +-- src/
|   |   +-- App.tsx             # Main app: chat state, API calls, PDF preview pane
|   |   +-- components/
|   |   |   +-- Sidebar.tsx         # Chat session list and navigation
|   |   |   +-- ChatArea.tsx        # Chat header, messages, Generate Memo button
|   |   |   +-- ChatInput.tsx       # Message input field
|   |   |   +-- MessageBubble.tsx   # Markdown: bold, bullets, clickable citation links
|   |   |   +-- MessageBubble.css   # Styling for message bubbles and lists
|   |   +-- index.css           # Global CSS and design tokens
|   |   +-- main.tsx            # React entry point
|   +-- package.json
|   +-- vite.config.ts
|
+-- downloads/                  # Scraped court PDFs (served via /api/downloads)
+-- uploads/                    # User-uploaded case documents (temp)
+-- .env                        # Environment variables (never commit)
```

---

## AI Agent Pipeline

### Node 1 — Intent Router (`intent_router.py`)
Classifies the user query as:
- **`INTERNAL`** — Legal question to be answered using the RAG pipeline (statutes + case laws).
- **`EXTERNAL`** — Request for an external link or portal; routed to web search.

### Node 2 — Query Decomposer (`query_decomposer.py`)
Breaks down the user query into 1–3 focused sub-queries with:
- Target agent assignment (`statute_agent` or `case_law_agent`)
- Qdrant metadata filters (year range, case type, laws cited)
- Complexity score

### Node 3 — Statute Agent (`statute_agent.py`)
- Embeds sub-queries using the Gemini embedding model.
- Queries the `statutes` Qdrant collection with jurisdiction and subcategory filters.
- Generates a grounded, section-cited legal answer from retrieved statutory chunks.

### Node 4 — Case Law Agent (`case_law_agent.py`)
- Embeds sub-queries and queries the `precedents_db` Qdrant collection.
- Applies strict metadata filters (court, year, laws cited) then **automatically relaxes** to pure vector similarity if no results are found.
- Returns scored, ranked chunk results with court and file metadata.

### Node 5 — Synthesis Agent (`synthesis_agent.py`)
- Formats all retrieved context chunks into a structured prompt including document URLs.
- Generates a conversational or formal response based on query context.
- For PDF memos: generates a structured legal memorandum (Executive Summary → Legal Analysis → Conclusion) and exports it as a PDF using `markdown-pdf`.
- All citations include **clickable hyperlinks** pointing to hosted court judgment PDFs (`/api/downloads`).

---

## Qdrant Vector Database Collections

| Collection | Layer | Description |
|---|---|---|
| `statutes` | 1 | Pakistani statutory laws — PPC, CrPC, PECA, Constitution, etc. |
| `precedents_db` | 2 | Supreme Court + High Court judgment chunks |
| `user_misl_db` | 3 | User-uploaded case documents (FIRs, witness statements, etc.) |

- **Embedding Model:** `models/gemini-embedding-001`
- **Vector Size:** `768` dimensions
- **Distance Metric:** Cosine

---

## Court Scrapers

| Scraper | Court | Method |
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

Scraped PDFs are saved to the `downloads/` folder and automatically served at:
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

The statute pipeline (Layer 1) is managed via the `Statutes_pipeline/` directory:

```bash
cd Statutes_pipeline
python run_pipeline.py
```

This scrapes statutory law text from Pakistani law sources and ingests it into the `statutes` Qdrant collection.

---

## Configuration

All shared constants are in `config.py`:

| Constant | Value | Description |
|---|---|---|
| `CHAT_MODEL` | `gemini-3.1-flash-lite` | Gemini model for generation |
| `EMBEDDING_MODEL` | `models/gemini-embedding-001` | Gemini embedding model |
| `VECTOR_SIZE` | `768` | Embedding dimensions |
| `STATUTES_COLLECTION` | `statutes` | Layer 1 Qdrant collection |
| `PRECEDENTS_COLLECTION` | `precedents_db` | Layer 2 Qdrant collection |
| `MISL_COLLECTION` | `user_misl_db` | Layer 3 Qdrant collection |
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
| `markdown-pdf` | Convert Markdown legal memos to PDF |
| `python-dotenv` | Environment variable management |
| `pydantic` | Data validation and API schemas |

---

## Adding a New Court Scraper

1. Create `scraper/courts/<court_code>.py`
2. Subclass `BaseScraper` from `scraper/base_scraper.py`
3. Implement the required methods:
   - `search_url` (property) — the target court portal URL
   - `submit_search(page, keyword)` — fills and submits the search form
   - `extract_pdf_links(page)` — scrapes all PDF download URLs from results
   - `go_to_next_page(page)` — returns `True` if pagination succeeded
4. Register it in `scraper/run_all.py`
5. Create a `run_<court>.py` runner script in the project root
