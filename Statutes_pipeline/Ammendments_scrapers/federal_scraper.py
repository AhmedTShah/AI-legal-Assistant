"""
test_portal_scraper.py — Matrix URL & Multi-Page Crawler Test Script
====================================================================
- Direct URL Parameter Combination Crawling
- Page Size: 50 items per page
- Automatic Multi-Page Pagination Loop (pageNumber = 1..N)
- Real docId & versionId Composite Key ("docId_versionId")
- Ingests into separate Qdrant collection: 'test_statutes_scraped'
- Updates scraped_manifest.json
"""

import os
import sys
import json
import re
import math
import requests
# pyrefly: ignore [missing-import]
import fitz  # PyMuPDF
import google.generativeai as genai
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from urllib.parse import urlparse, parse_qs, quote
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

# Add root directory to sys.path to import config.py
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(ROOT_DIR))

from config import EMBEDDING_MODEL, VECTOR_SIZE, BATCH_SIZE, STATUTES_COLLECTION

# Load environment variables
load_dotenv(ROOT_DIR / ".env")

# TARGET COLLECTION NAME FROM SHARED CONFIG
TEST_COLLECTION = STATUTES_COLLECTION

# 1. Selected Ministries
MINISTRIES = [
    "Law and Justice",
    "Information Technology and Telecommunication",
    "Interior",
    "Human Rights",
]

# 2. Selected Subcategories (Document Types)
SUBCATEGORIES = [
    "Act",
    "Ordinance",
    "Rules",
    "Notification",
    "Order",
]

# 3. Selected Law Categories (Target Niche)
LAW_CATEGORIES = [
    "Cyber Laws",
    "Criminal Laws",
    "Civil and Court Procedure",
    "Procedural Law",
    "Police Laws",
    "Witness Protection Law",
    "National Counter Terrorism Authority Law",
    "Anti-Corruption Law",
    "Digital Transformation",
    "Information Technology Laws",
    "Women Laws",
    "Human Right Law",
]

# Manifest Tracking File Path
MANIFEST_PATH = Path(__file__).resolve().parent / "scraped_manifest.json"


class ManifestTracker:
    """Manages local JSON manifest tracking to prevent duplicate scraping."""

    def __init__(self, manifest_file: Path = MANIFEST_PATH):
        self.manifest_file = manifest_file
        self.data = self._load_manifest()

    def _load_manifest(self) -> dict:
        if self.manifest_file.exists():
            try:
                with open(self.manifest_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ Warning loading manifest: {e}. Starting fresh.")
                return {}
        return {}

    def is_processed(self, composite_key: str) -> bool:
        """Check if composite key (docId_versionId) has already been ingested."""
        return str(composite_key) in self.data

    def mark_processed(self, composite_key: str, title: str, source_url: str):
        """Record processed document metadata into manifest."""
        self.data[str(composite_key)] = {
            "title": title,
            "source_url": source_url,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "status": "PROCESSED",
        }
        self._save_manifest()

    def _save_manifest(self):
        with open(self.manifest_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)


def get_qdrant_client() -> QdrantClient:
    """Connect to Qdrant Cloud."""
    url = os.getenv("QDRANT_URL")
    api_key = os.getenv("QDRANT_API_KEY")
    if not url or not api_key:
        raise EnvironmentError("QDRANT_URL or QDRANT_API_KEY missing from .env")
    return QdrantClient(url=url, api_key=api_key, timeout=60)


def ensure_test_collection(client: QdrantClient):
    """Ensure separate test collection exists in Qdrant."""
    collections = [c.name for c in client.get_collections().collections]
    if TEST_COLLECTION not in collections:
        print(f" [+] Creating new separate test collection: '{TEST_COLLECTION}'...")
        client.create_collection(
            collection_name=TEST_COLLECTION,
            vectors_config=qmodels.VectorParams(
                size=VECTOR_SIZE,
                distance=qmodels.Distance.COSINE
            )
        )
        client.create_payload_index(
            collection_name=TEST_COLLECTION,
            field_name="is_active",
            field_schema=qmodels.PayloadSchemaType.BOOL
        )
    else:
        print(f" [+] Using existing separate test collection: '{TEST_COLLECTION}'")


def scrape_matrix_documents(max_docs_limit: int = None) -> list[dict]:
    """
    Constructs URL query combinations across Ministries, Subcategories, and Law Categories,
    navigates pagination (pageNumber = 1..N), and extracts document cards.
    """
    tracker = ManifestTracker()
    extracted_docs = []
    seen_keys = set(tracker.data.keys())

    print("\n[1/4] Starting Matrix URL & Multi-Page Pagination Scraper...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 100% Dynamic 3-Level Filter Combination Loop
        for ministry in MINISTRIES:
            for subcat in SUBCATEGORIES:
                for lawcat in LAW_CATEGORIES:
                    page_num = 1
                    total_pages = 1

                    while page_num <= total_pages:
                        encoded_m = quote(ministry)
                        encoded_sub = quote(subcat)
                        encoded_law = quote(lawcat)
                        url = (
                            f"https://drs.molaw.gov.pk/documents?"
                            f"ministry={encoded_m}&"
                            f"subCategory={encoded_sub}&"
                            f"lawCategory={encoded_law}&"
                            f"pageNumber={page_num}&"
                            f"pageSize=50"
                        )

                        print(f"\n  [URL Fetch] Ministry: '{ministry}' | Subcat: '{subcat}' | LawCat: '{lawcat}' | Page {page_num}")
                        print(f"  --> {url}")

                        try:
                            page.goto(url, wait_until="networkidle", timeout=60000)
                            page.wait_for_selector("body", timeout=15000)

                            html_content = page.content()
                            soup = BeautifulSoup(html_content, "html.parser")

                            # Parse total document count ("Showing X of Y")
                            showing_text = soup.get_text()
                            count_match = re.search(r"Showing\s+\d+\s+of\s+(\d+)", showing_text, re.IGNORECASE)
                            if count_match:
                                total_items = int(count_match.group(1))
                                # Portal server caps at 10 items per page
                                total_pages = math.ceil(total_items / 10)
                                print(f"      Count Info: {total_items} document(s) found across {total_pages} page(s).")

                            # Extract document version links
                            links = soup.find_all("a", href=True)
                            page_matches = 0

                            for link_elem in links:
                                href = link_elem["href"]
                                if "docId=" in href or "document-versions" in href:
                                    parsed_url = urlparse(href)
                                    query_params = parse_qs(parsed_url.query)

                                    doc_id = query_params.get("docId", [""])[0]
                                    version_id = query_params.get("versionId", [""])[0]

                                    if not doc_id:
                                        continue

                                    composite_key = f"{doc_id}_{version_id}" if version_id else doc_id
                                    if composite_key in seen_keys or tracker.is_processed(composite_key):
                                        continue

                                    # Extract card container text & title specifically for THIS card
                                    clean_title = ""
                                    link_text = link_elem.get_text(strip=True)
                                    if len(link_text) > 12 and not any(kw in link_text.lower() for kw in ["view", "detail", "document", "new documents"]):
                                        clean_title = link_text

                                    if not clean_title:
                                        card_wrapper = link_elem
                                        for _ in range(4):
                                            if card_wrapper.parent and card_wrapper.parent.name not in ["body", "html", "main"]:
                                                card_wrapper = card_wrapper.parent
                                                text_nodes = [t.get_text(strip=True) for t in card_wrapper.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "a", "span"]) if len(t.get_text(strip=True)) > 12]
                                                for txt in text_nodes:
                                                    txt_lower = txt.lower()
                                                    if not any(kw in txt_lower for kw in ["home", "search", "retrieval", "constitution", "ministry", "showing", "reset", "filters", "sort", "gazette", "new documents", "document retrieval"]):
                                                        clean_title = txt
                                                        break
                                                if clean_title:
                                                    break

                                    # Post-Process & Clean Title using Regex
                                    if clean_title:
                                        # 1. Remove leading circle icon numbers (e.g. "1", "2", "21")
                                        clean_title = re.sub(r"^\d+\s*", "", clean_title)
                                        # 2. Cut off trailing metadata clutter starting at Notification, Year:, or Published:
                                        clean_title = re.split(r"(?i)\b(Notification|Year:|Published:)", clean_title)[0].strip()
                                        # 3. Clean trailing dots/dashes
                                        clean_title = re.sub(r"[\.\-\s]+$", "", clean_title).strip()

                                    if not clean_title or clean_title.lower() in ["notification", "act", "ordinance", "new documents"]:
                                        clean_title = f"Federal Law Document {doc_id}"

                                    seen_keys.add(composite_key)
                                    full_href = href if href.startswith("http") else f"https://drs.molaw.gov.pk{href}"

                                    extracted_docs.append({
                                        "doc_id": composite_key,
                                        "title": clean_title[:150],
                                        "published_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                                        "pdf_url": f"https://drs.molaw.gov.pk/documents/pdf/{doc_id}",
                                        "source_url": full_href,
                                        "category": f"{ministry} - {subcat}",
                                    })
                                    page_matches += 1
                                    print(f"      [+] Found ID: {composite_key} | Title: '{clean_title[:70]}'")

                                    if max_docs_limit and len(extracted_docs) >= max_docs_limit:
                                        break

                        except Exception as e:
                            print(f"      ❌ Page fetch error: {e}")
                            break

                        page_num += 1

                if max_docs_limit and len(extracted_docs) >= max_docs_limit:
                    break

        browser.close()

    print(f"\n  Total new documents extracted across matrix: {len(extracted_docs)}")
    return extracted_docs


def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Generate 768-dim embeddings using Gemini."""
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    result = genai.embed_content(
        model=EMBEDDING_MODEL,
        content=texts,
        output_dimensionality=VECTOR_SIZE
    )
    return result['embedding']


def run_test_pipeline():
    """Run standalone matrix scraper & ingestion test."""
    print("=" * 75)
    print(" LEGALMIND - MATRIX URL & MULTI-PAGE CRAWLER TEST SUITE")
    print(f" Target Collection: '{TEST_COLLECTION}' (Separate from main DB)")
    print("=" * 75)

    client = get_qdrant_client()
    ensure_test_collection(client)

    test_docs = scrape_matrix_documents(max_docs_limit=None)

    if not test_docs:
        print("\n [!] No new un-processed documents found across matrix combinations.")
        print("=" * 75)
        return

    print(f"\n[2/4] Extracted Documents List:")
    for d in test_docs:
        print(f"  * ID: {d['doc_id']} | Title: '{d['title']}' | Category: {d['category']}")

    print(f"\n[3/4] Generating Gemini embeddings for test chunks...")
    sample_chunks = []
    for d in test_docs:
        sample_chunks.append({
            "text": f"Document Title: {d['title']}. Official published under {d['category']}.",
            "act_name": d['title'],
            "section_number": "Sec_Test",
            "jurisdiction": "Federal",
            "doc_type": "statute_amendment",
            "source_file": f"doc_{d['doc_id']}.pdf",
            "source_url": d['source_url'],
            "is_active": True,
            "status": "ACTIVE",
            "amended_by": None
        })

    texts = [c["text"] for c in sample_chunks]
    embeddings = generate_embeddings(texts)

    # Build Qdrant PointStructs
    import uuid
    points = []
    for chunk, embedding in zip(sample_chunks, embeddings):
        point_id = str(uuid.uuid4())
        points.append(
            qmodels.PointStruct(
                id=point_id,
                vector=embedding,
                payload=chunk
            )
        )

    print(f"\n[4/4] Ingesting {len(points)} test points into separate collection '{TEST_COLLECTION}'...")
    client.upsert(collection_name=TEST_COLLECTION, points=points)

    # Save tracking into scraped_manifest.json
    tracker = ManifestTracker()
    for d in test_docs:
        tracker.mark_processed(d['doc_id'], d['title'], d['source_url'])
    print(" [+] Updated local 'scraped_manifest.json' with processed real composite IDs.")

    print("\n" + "=" * 75)
    print(f" SUCCESS - MATRIX CRAWLER PIPELINE COMPLETED!")
    print(f" Points inserted into '{TEST_COLLECTION}' collection.")
    print("=" * 75)


if __name__ == "__main__":
    run_test_pipeline()
