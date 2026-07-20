# LegalMind — Layer 2 & 3: Precedents + User Case Files

> **Part of the LegalMind RAG-based Legal Research Assistant** for Pakistani criminal and cyber law.
> This folder covers **Layer 2** (court judgments → `precedents_db`) and **Layer 3** (user-uploaded case docs → `user_misl_db`).
> Layer 1 (statutes → `statutes_db`) is managed separately by a collaborator — do not touch that collection.

---

## Folder Structure

```
LegalMind-Layer2/
├── scraper/
│   ├── base_scraper.py         # Shared Playwright async base class
│   ├── run_all.py              # Entry point: runs all court scrapers concurrently
│   ├── courts/
│   │   ├── lhc.py              # Lahore High Court      (fully implemented)
│   │   ├── shc.py              # Sindh High Court       (stub — implement selectors)
│   │   ├── ihc.py              # Islamabad High Court   (stub)
│   │   ├── scp.py              # Supreme Court          (stub)
│   │   └── phc.py              # Peshawar High Court    (stub)
│   └── utils/
│       ├── pdf_extractor.py    # pdfplumber text extraction
│       ├── chunker.py          # Token-aware sliding-window chunker (tiktoken)
│       └── embedder.py         # OpenAI text-embedding-3-small generation
│
├── pipeline/
│   ├── qdrant_client.py        # Qdrant connection + collection bootstrap
│   ├── ingest_precedents.py    # Judgment PDF → precedents_db
│   └── ingest_misl.py          # User docs → user_misl_db
│
├── uploads/                    # Temp folder for user-uploaded documents (git-ignored contents)
├── downloads/                  # Auto-created; court PDFs land here (git-ignored)
│
├── .env.example                # Credential template — copy to .env and fill in
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Qdrant Collections (my responsibility)

| Collection | Layer | Description |
|---|---|---|
| `precedents_db` | 2 | Supreme Court + High Court judgment chunks |
| `user_misl_db` | 3 | FIRs, witness statements, depositions |

> `statutes_db` is **partner-managed** — never modify it from this codebase.

- Vector size: **1536** (OpenAI `text-embedding-3-small`)  
- Distance metric: **Cosine**

---

## Setup

### 1. Install dependencies

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure credentials

```bash
copy .env.example .env
# Open .env and fill in QDRANT_API_KEY and OPENAI_API_KEY
```

### 3. Bootstrap Qdrant collections (first time only)

```python
from pipeline.qdrant_client import get_qdrant_client, ensure_collections
client = get_qdrant_client()
ensure_collections(client)
```

---

## Usage

### Run LHC scraper (default keyword: PECA)

```bash
python -m scraper.courts.lhc
python -m scraper.courts.lhc --keyword "cybercrime" --pages 5 --no-headless
```

### Run all scrapers (stubs are skipped gracefully)

```bash
python -m scraper.run_all --keyword "PECA" --pages 10
python -m scraper.run_all --keyword "PECA" --courts lhc scp
```

### Ingest judgments → precedents_db

```bash
python -m pipeline.ingest_precedents \
    --pdf downloads/judgment_2023.pdf \
    --court LHC --year 2023 \
    --laws-cited "PECA,PPC" --case-type cybercrime

# Batch ingest entire downloads folder
python -m pipeline.ingest_precedents --dir downloads/ --court LHC
```

### Ingest user documents → user_misl_db

```bash
python -m pipeline.ingest_misl \
    --file uploads/fir_001.pdf \
    --doc-type FIR \
    --case-number "123/2024" \
    --uploaded-by "advocate@firm.com"
```

---

## Adding a New Court Scraper

1. Create `scraper/courts/<court_code>.py`
2. Subclass `BaseScraper`
3. Implement the 3 abstract methods:
   - `search_url` (property)
   - `submit_search(page, keyword)`
   - `extract_pdf_links(page)`
   - `go_to_next_page(page)`
4. Register it in `scraper/run_all.py`

---

## Architecture

```
[Court Website]
      | Playwright async scraper
      v
[downloads/*.pdf]
      | pdfplumber
      v
[raw text]
      | tiktoken chunker (500 tok / 50 overlap)
      v
[text chunks + metadata]
      | OpenAI text-embedding-3-small
      v
[1536-dim vectors]
      | qdrant-client upsert
      v
[precedents_db / user_misl_db]
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `playwright` | Async browser automation |
| `pdfplumber` | PDF text extraction |
| `qdrant-client` | Qdrant vector DB |
| `openai` | Embedding generation |
| `python-dotenv` | Credential loading |
| `tiktoken` | Token-accurate chunking |
| `httpx` | PDF file downloads |
