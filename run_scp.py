"""
run_scp.py — Scrape and ingest Supreme Court of Pakistan (SCP) judgments for 2024–2026.

This script runs SCPScraper sequentially for years 2024, 2025, and 2026,
downloads the judgment PDFs using Chrome stealth channel, applies a high-fidelity
criminal/cybercrime keyword filter on the extracted text of the PDFs,
and ingests the matching cases into the Qdrant database.
"""

import asyncio
import logging
from pathlib import Path
from qdrant_client import QdrantClient

from scraper.courts.scp import SCPScraper
from pipeline.qdrant_client import get_qdrant_client, ensure_collections
from pipeline.ingest_precedents import ingest_pdf, COLLECTION_NAME
from scraper.utils.pdf_extractor import extract_text_from_pdf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("run_scp")

# High-fidelity criminal/cybercrime keywords for filtering Supreme Court cases
CRIMINAL_KEYWORDS = [
    "criminal", "crl", "cr.a", "crl.a", "crl.p", "crl.m", "bail", "ppc", "crpc", "cr.p.c",
    "anti-terrorism", "ata", "police", "fir", "offence", "accused",
    "prosecution", "complainant", "cybercrime", "peca", "fia",
    "conviction", "sentence", "acquittal", "trial court", "penal code",
    "murder", "narcotics", "cnsa", "bail after arrest", "bail before arrest",
    "habeas corpus", "kidnapping", "theft", "dacoity", "custody", "prison"
]

CYBERCRIME_KEYWORDS = [
    "cybercrime", "peca", "fia", "cyber", "electronic transactions",
    "social media", "hacking", "unauthorized access", "online fraud"
]


def is_criminal_case(text: str) -> tuple[bool, str]:
    """
    Check if the document is related to criminal or cybercrime law.
    Returns (is_match, classification).
    """
    text_lower = text.lower()
    
    # 1. Check cybercrime first
    if any(kw in text_lower for kw in CYBERCRIME_KEYWORDS):
        return True, "cybercrime"
        
    # 2. Check general criminal terms
    if any(kw in text_lower for kw in CRIMINAL_KEYWORDS):
        return True, "criminal"
        
    return False, ""


async def scrape_year(year: int):
    logger.info("========================================")
    logger.info("Starting SCP Scraping for Year: %d", year)
    logger.info("========================================")
    
    scraper = SCPScraper(keyword="criminal", year=year, headless=True)
    downloaded_paths = await scraper.run()
    logger.info("Completed scraping for %d. Downloaded %d PDFs.", year, len(downloaded_paths))
    return downloaded_paths


def ingest_downloaded_files(downloaded_files: list[Path], client: QdrantClient):
    logger.info("Starting filtering and ingestion of SCP judgments...")
    ingested_count = 0
    skipped_count = 0
    
    for pdf_path in downloaded_files:
        if not pdf_path.exists():
            continue
            
        # 1. Check if already ingested in Qdrant (idempotency check)
        from qdrant_client.http import models as qmodels
        try:
            existing = client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="file_name",
                            match=qmodels.MatchValue(value=pdf_path.name)
                        )
                    ]
                ),
                limit=1,
                with_payload=False,
                with_vectors=False
            )
            if existing[0]:
                logger.info("PDF %s is already ingested — skipping.", pdf_path.name)
                continue
        except Exception as exc:
            logger.warning("Could not check duplicate status for %s: %s", pdf_path.name, exc)

        # 2. Extract text for classification filtering
        try:
            text, _ = extract_text_from_pdf(pdf_path)
            if not text:
                logger.warning("Could not extract text from %s — running ingestion directly.", pdf_path.name)
                match = True
                case_type = "criminal"
            else:
                match, case_type = is_criminal_case(text)
                
            if not match:
                logger.info("Skipping non-criminal SCP case: %s", pdf_path.name)
                skipped_count += 1
                continue
                
            logger.info("Matched SCP case %s as classification: %s", pdf_path.name, case_type)
            
            # 3. Ingest matching cases
            chunks_added = ingest_pdf(
                pdf_path=pdf_path,
                client=client,
                court="SCP",
                year=None, # Inferred from filename automatically
                source_url="", # Reconstructed automatically by our pipeline update
                laws_cited=[],
                case_type=case_type
            )
            if chunks_added > 0:
                ingested_count += 1
                
        except Exception as e:
            logger.error("Failed to process/ingest SCP case %s: %s", pdf_path.name, e, exc_info=True)
            
    logger.info("Ingestion summary: Ingested %d criminal cases, Skipped %d non-criminal cases.", ingested_count, skipped_count)


async def main():
    # 1. Initialize Qdrant Client
    client = get_qdrant_client()
    ensure_collections(client)
    
    # 2. Scrape years 2021 through 2026 sequentially
    all_downloaded = []
    for year in [2021, 2022, 2023, 2024, 2025, 2026]:
        try:
            downloaded = await scrape_year(year)
            all_downloaded.extend(downloaded)
        except Exception as e:
            logger.error("Scraper failed for year %d: %s", year, e, exc_info=True)
            
    # 3. Filter and Ingest downloaded files
    if all_downloaded:
        ingest_downloaded_files(all_downloaded, client)
    else:
        logger.warning("No new files downloaded by the scraper.")


if __name__ == "__main__":
    asyncio.run(main())
