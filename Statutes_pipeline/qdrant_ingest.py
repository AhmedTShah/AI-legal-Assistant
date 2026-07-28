"""
qdrant_ingest.py
================
Qdrant database ingestion pipeline for LawMind parsed legal chunks.

Reads the parsed chunks by invoking `lawmind_ingest.py` parsing logic,
generates embeddings using the Gemini Embedding API, and upserts them
into the Qdrant vector database.
"""

import os
import sys
import time
import argparse
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

# Override DNS resolution for Qdrant Cloud to bypass local DNS issues
import socket
_original_getaddrinfo = socket.getaddrinfo
def _custom_getaddrinfo(host, port, *args, **kwargs):
    if host == "1f03f5d6-5fc1-441c-9c39-ab06f32a88f9.eu-central-1-0.aws.cloud.qdrant.io":
        return _original_getaddrinfo("3.126.6.235", port, *args, **kwargs)
    return _original_getaddrinfo(host, port, *args, **kwargs)
socket.getaddrinfo = _custom_getaddrinfo

# Add Statutes_pipeline directory and parent directory to sys.path to import modules
sys.path.append(str(Path(__file__).resolve().parent))
sys.path.append(str(Path(__file__).resolve().parent.parent))

from lawmind_ingest import process_all_pdfs, LegalChunk, DocSubcategory, PDF_DIR
from config import STATUTES_COLLECTION, EMBEDDING_MODEL, VECTOR_SIZE, BATCH_SIZE

# Load environment variables from .env in parent folder (LawMind/)
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)


def _get_qdrant_client():
    url = os.getenv("QDRANT_URL")
    api_key = os.getenv("QDRANT_API_KEY")
    if not url:
        print("❌ Error: QDRANT_URL environment variable is not set!")
        sys.exit(1)

    client = QdrantClient(
        url     = url,
        api_key = api_key,
        timeout = 60,
    )
    
    # Ensure collection exists
    try:
        existing = [c.name for c in client.get_collections().collections]
        if STATUTES_COLLECTION not in existing:
            from qdrant_client.models import Distance, VectorParams
            print(f"Creating collection '{STATUTES_COLLECTION}'...")
            client.create_collection(
                collection_name=STATUTES_COLLECTION,
                vectors_config=VectorParams(
                    size=VECTOR_SIZE,
                    distance=Distance.COSINE
                )
            )
            print(f"✅ Collection '{STATUTES_COLLECTION}' created successfully!")
    except Exception as exc:
        print(f"❌ Qdrant connection error: {exc}")
        sys.exit(1)

    return client, STATUTES_COLLECTION


def _generate_batch_embeddings(batch_texts: List[str]) -> List[List[float]]:
    """Generate embeddings for a batch of texts using a single Gemini API key.
    Retries with exponential backoff on 429 / transient errors."""
    import google.generativeai as genai
    from google.api_core.exceptions import ResourceExhausted, GoogleAPICallError, DeadlineExceeded, ServiceUnavailable
    import re

    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        print("❌ Error: GEMINI_API_KEY environment variable is not set!")
        sys.exit(1)

    # Use only the first key if multiple are present
    api_key = gemini_key.split(",")[0].strip()
    genai.configure(api_key=api_key)

    max_retries = 10
    for attempt in range(1, max_retries + 1):
        try:
            # Truncate each text to max 8000 characters (~2000 tokens) to stay within Gemini limits
            # and prevent Token-Per-Minute (TPM) quota exhaustion.
            safe_texts = [t[:8000] for t in batch_texts]
            result = genai.embed_content(
                model=EMBEDDING_MODEL,
                content=safe_texts,
                output_dimensionality=VECTOR_SIZE,
            )
            return result["embedding"]
        except (ResourceExhausted, GoogleAPICallError, DeadlineExceeded, ServiceUnavailable) as e:
            err_str = str(e)
            is_429 = "429" in err_str or "quota" in err_str.lower()

            if is_429:
                # Parse retry delay from Google's response, default 60s
                retry_delay = 60.0
                match = re.search(r"retry in ([\d\.]+)s", err_str, re.IGNORECASE)
                if match:
                    retry_delay = float(match.group(1))
                print(f"  ⏳ 429 Rate limited (attempt {attempt}/{max_retries}). Waiting {retry_delay:.0f}s...")
                time.sleep(retry_delay)
            else:
                backoff = min(5 * attempt, 30)
                print(f"  ⚠️ API error (attempt {attempt}/{max_retries}): {err_str[:100]}. Retrying in {backoff}s...")
                time.sleep(backoff)

            if attempt == max_retries:
                print("  ❌ Max retries reached. Giving up on this batch.")
                raise e
        except Exception as e:
            print(f"  ❌ Unexpected error: {e}")
            raise e


def _generate_embeddings(texts: List[str]) -> List[List[float]]:
    """Generate embeddings for a list of texts, splitting into batches."""
    all_emb: List[List[float]] = []
    total = (len(texts) - 1) // BATCH_SIZE + 1

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i: i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        print(f"  Embedding batch {batch_num}/{total} ({len(batch)} texts)...")
        emb = _generate_batch_embeddings(batch)
        all_emb.extend(emb)

    return all_emb


def _upsert_to_qdrant(
    client, col: str, chunks: List[LegalChunk], embeddings
) -> None:
    points = [
        PointStruct(
            id      = c.get_point_id(),
            vector  = e,
            payload = c.to_qdrant_payload(),
        )
        for c, e in zip(chunks, embeddings)
    ]

    total = (len(points) - 1) // BATCH_SIZE + 1
    for i in range(0, len(points), BATCH_SIZE):
        batch = points[i: i + BATCH_SIZE]
        bn    = i // BATCH_SIZE + 1
        for attempt in range(1, 4):
            try:
                client.upsert(collection_name=col, points=batch)
                print(f"  Upsert batch {bn}/{total} ({len(batch)} points)")
                break
            except Exception as exc:
                if attempt < 3:
                    print(f"  Retry {attempt}/3: {exc}")
                    time.sleep(3)
                else:
                    raise


def run(
    dry_run:          bool          = False,
    subcat_filter:    Optional[str] = None,
    import_json_path: Optional[str] = None,
) -> None:
    print("=" * 62)
    print("  LawMind Legal Qdrant Ingestion Pipeline")
    print("=" * 62)

    cache_file = Path(__file__).resolve().parent / "parsed_laws_cache.json"

    # Decide where to load chunks from
    load_path = None
    if import_json_path:
        load_path = Path(import_json_path)
    elif cache_file.exists():
        print(f"✨ Found cached parsed chunks in '{cache_file.name}'!")
        print(f"Using cache to save 15 mins of parsing time. (Delete '{cache_file.name}' if you want to force re-parse).")
        load_path = cache_file

    if load_path:
        import json
        print(f"Loading chunks from '{load_path}'...")
        with open(load_path, "r", encoding="utf-8") as f:
            payloads = json.load(f)
        
        chunks = []
        for p in payloads:
            c = LegalChunk(
                text                = p.get("text", ""),
                act_name            = p.get("act_name", ""),
                jurisdiction        = p.get("jurisdiction", ""),
                source_file         = p.get("source_file", ""),
                doc_type            = p.get("doc_type", "statute"),
                subcategory         = p.get("subcategory", ""),
                year                = p.get("year"),
                section_number      = p.get("section_number"),
                section_title       = p.get("section_title", ""),
                parent_section      = p.get("parent_section"),
                numbering_unit      = p.get("numbering_unit", "section"),
                is_active           = p.get("is_active", True),
                status              = p.get("status", "ACTIVE"),
                amendment_history   = p.get("amendment_history", []),
                whole_act_repeals   = p.get("whole_act_repeals", []),
                whole_act_revivals  = p.get("whole_act_revivals", []),
                deleted_ranges      = p.get("deleted_ranges", []),
                cross_references    = p.get("cross_references", {"internal": [], "external": []}),
                enacting_instrument = p.get("enacting_instrument"),
                offence             = p.get("offence", ""),
                arrestable          = p.get("arrestable", ""),
                bailable            = p.get("bailable", ""),
                compoundable        = p.get("compoundable", ""),
                punishment          = p.get("punishment", ""),
                triable_by          = p.get("triable_by", ""),
                sro_number          = p.get("sro_number", ""),
                gazette_number      = p.get("gazette_number", ""),
                issuing_ministry    = p.get("issuing_ministry", ""),
                notification_date   = p.get("notification_date", ""),
                version             = p.get("version", "v1")
            )
            if subcat_filter and c.subcategory != subcat_filter:
                continue
            chunks.append(c)
        print(f"Loaded {len(chunks)} chunks.")
    else:
        print("Parsing PDFs (this might take up to 15 minutes)...")
        chunks = process_all_pdfs(PDF_DIR, filter_subcat=subcat_filter)
        
        # Save to cache file automatically so next time is instant!
        if chunks:
            import json
            print(f"Saving parsed chunks to '{cache_file.name}' for faster future runs...")
            payload_list = [c.to_qdrant_payload() for c in chunks]
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(payload_list, f, indent=2, ensure_ascii=False)

    if not chunks:
        print("No chunks produced. Exiting.")
        return

    if dry_run:
        print(f"\n  Total chunks: {len(chunks)}")
        print("  --dry-run: generating embeddings to verify API client, skipping Qdrant upload...")
        # Verify embeddings generation (only first few to save costs/time, or all)
        sample_texts = [c.text for c in chunks[:min(5, len(chunks))]]
        print(f"  Testing embeddings generation on a sample of {len(sample_texts)} chunks...")
        embeddings = _generate_embeddings(sample_texts)
        if embeddings:
            print("  ✅ Embeddings generation verified successfully.")
        print("  Qdrant upsert skipped.")
        return

    client, col = _get_qdrant_client()

    print("\n  Checking Qdrant for already ingested chunks to support resume...")
    existing_ids = set()
    all_ids = [c.get_point_id() for c in chunks]
    for start_idx in range(0, len(all_ids), 1000):
        batch_ids = all_ids[start_idx : start_idx + 1000]
        try:
            retrieved = client.retrieve(
                collection_name=col,
                ids=batch_ids,
                with_payload=False,
                with_vectors=False
            )
            for p in retrieved:
                existing_ids.add(str(p.id))
        except Exception:
            pass

    original_count = len(chunks)
    chunks = [c for c in chunks if str(c.get_point_id()) not in existing_ids]
    skipped_count = original_count - len(chunks)

    if skipped_count > 0:
        print(f"  ⏭️ Skipped {skipped_count} chunks that already exist in Qdrant.")

    if not chunks:
        print("  🎉 All chunks are already successfully ingested into Qdrant! Nothing to do.")
        return

    print(f"  Processing {len(chunks)} remaining chunks batch-by-batch...")

    # --- Rate-limit-safe settings ---
    # Gemini free tier: 15 RPM.
    # Sending 20 texts (max 8k chars each) keeps token count safe and avoids 429.
    EMBED_BATCH = 20            # texts per batch
    INTER_REQUEST_DELAY = 3     # seconds between batches

    total_chunks = len(chunks)
    total_batches = (total_chunks - 1) // EMBED_BATCH + 1

    print(f"\n  Processing {total_chunks} texts in batches of {EMBED_BATCH} (Embed + Upsert live)...")

    from qdrant_client.models import PointStruct

    for b_idx in range(0, total_chunks, EMBED_BATCH):
        batch_chunks = chunks[b_idx : b_idx + EMBED_BATCH]
        batch_texts = [c.text for c in batch_chunks]
        b_num = b_idx // EMBED_BATCH + 1

        print(f"    [{b_num}/{total_batches}] Generating embeddings for {len(batch_texts)} texts...", end=" ", flush=True)
        batch_emb = _generate_batch_embeddings(batch_texts)
        print("OK", end=" -> ", flush=True)

        # Prepare points
        points = []
        for c, emb in zip(batch_chunks, batch_emb):
            payload = c.to_qdrant_payload()
            # Truncate payload text to 10000 characters to prevent database bloat
            if len(payload.get("text", "")) > 10000:
                payload["text"] = payload["text"][:10000] + "\n... [TRUNCATED DUE TO SIZE]"
            points.append(
                PointStruct(
                    id      = c.get_point_id(),
                    vector  = emb,
                    payload = payload,
                )
            )

        # Upsert immediately to Qdrant so it updates LIVE in dashboard
        print(f"Upserting to Qdrant...", end=" ", flush=True)
        for upsert_attempt in range(1, 4):
            try:
                client.upsert(collection_name=col, points=points)
                print("✅ Done")
                break
            except Exception as exc:
                if upsert_attempt < 3:
                    print(f"⚠️ Retry {upsert_attempt}/3...", end=" ", flush=True)
                    time.sleep(3)
                else:
                    print("❌ FAILED")
                    raise exc

        # Proactive delay between API calls to stay under RPM limit
        if b_num < total_batches:
            time.sleep(INTER_REQUEST_DELAY)

    print(f"\n  Done — Ingested all remaining {len(chunks)} chunks into '{col}'.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="LawMind Ingestion Pipeline to Qdrant"
    )
    ap.add_argument("--dry-run",     action="store_true",
                    help="Parse only and test embeddings, skip Qdrant upsert")
    ap.add_argument("--type",        choices=[e.value for e in DocSubcategory],
                    help="Process only this subcategory")
    ap.add_argument("--import-json", type=str, metavar="FILE",
                    help="Ingest pre-parsed chunks from JSON instead of parsing PDFs")
    args = ap.parse_args()

    run(
        dry_run          = args.dry_run,
        subcat_filter    = args.type,
        import_json_path = args.import_json,
    )
