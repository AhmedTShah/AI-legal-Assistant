"""
run_ihc.py — Scrape and ingest Islamabad High Court (IHC) judgments.

Flags:
  --scrape-only        Download PDFs only, skip ingestion
  --years 2025 2026    Only process specific years (default: 2024 2025 2026)

Examples:
  python run_ihc.py                          # scrape + ingest 2024-2026
  python run_ihc.py --scrape-only            # download only, all years
  python run_ihc.py --scrape-only --years 2025 2026   # download 2025+2026 only
  python run_ihc.py --years 2025 2026        # scrape + ingest 2025+2026 only
"""

import sys
import asyncio
import logging
from pathlib import Path
from qdrant_client import QdrantClient

from scraper.courts.ihc import IHCScraper
from pipeline.qdrant_client import get_qdrant_client, ensure_collections
from pipeline.ingest_precedents import ingest_pdf, COLLECTION_NAME
from scraper.utils.pdf_extractor import extract_text_from_pdf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("run_ihc")

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
    
    if any(kw in text_lower for kw in CYBERCRIME_KEYWORDS):
        return True, "cybercrime"
        
    if any(kw in text_lower for kw in CRIMINAL_KEYWORDS):
        return True, "criminal"
        
    return False, "non_criminal"


async def scrape_year(year: int) -> list[Path]:
    logger.info("========================================")
    logger.info("Starting IHC Scraping for Year: %d", year)
    logger.info("========================================")
    
    scraper = IHCScraper(keyword="criminal", year=year, headless=True)
    downloaded_files = await scraper.run()
    
    logger.info("Completed scraping for %d. Downloaded %d PDFs.", year, len(downloaded_files))
    return downloaded_files


def get_existing_ihc_filenames(client: QdrantClient) -> set:
    existing_names = set()
    offset = None
    try:
        while True:
            res = client.scroll(
                collection_name=COLLECTION_NAME,
                limit=2000,
                offset=offset,
                with_payload=["file_name"],
                with_vectors=False
            )
            points, next_offset = res
            for p in points:
                if p.payload and "file_name" in p.payload:
                    existing_names.add(p.payload["file_name"])
            if not next_offset:
                break
            offset = next_offset
    except Exception as exc:
        logger.warning("Could not pre-fetch existing file names from Qdrant: %s", exc)
    return existing_names


def process_single_pdf(pdf_path: Path, client: QdrantClient, existing_set: set) -> tuple[str, int]:
    """
    Worker function to process a single PDF.
    Returns ('ingested'|'skipped'|'existing'|'error', chunks_count)
    """
    if not pdf_path.exists():
        return ("skipped", 0)

    if pdf_path.name in existing_set:
        logger.debug("PDF %s is already ingested — skipping.", pdf_path.name)
        return ("existing", 0)

    try:
        text, _ = extract_text_from_pdf(pdf_path)
        if not text:
            logger.warning("Could not extract text from %s — skipping.", pdf_path.name)
            pdf_path.unlink(missing_ok=True)
            return ("skipped", 0)

        match, case_type = is_criminal_case(text)
        if not match:
            logger.info("Skipping non-criminal IHC case: %s", pdf_path.name)
            pdf_path.unlink(missing_ok=True)
            return ("skipped", 0)

        year = 2025
        if "_" in pdf_path.name:
            parts = pdf_path.name.split("_")
            if parts[0].isdigit() and len(parts[0]) == 4:
                year = int(parts[0])

        chunks_added = ingest_pdf(
            pdf_path=pdf_path,
            client=client,
            court="ihc",
            year=year,
            case_type=case_type
        )
        logger.info("Ingested %s (%d chunks added).", pdf_path.name, chunks_added)
        return ("ingested", chunks_added)

    except Exception as exc:
        logger.error("Failed to process/ingest IHC case %s: %s", pdf_path.name, exc)
        return ("error", 0)


def ingest_downloaded_files(downloaded_files: list[Path], client: QdrantClient, max_workers: int = 1):
    logger.info("Starting high-speed multithreaded filtering and ingestion of IHC judgments...")
    logger.info("Pre-fetching existing ingested IHC filenames from Qdrant...")
    existing_set = get_existing_ihc_filenames(client)
    logger.info("Found %d already-ingested IHC files in precedents_db.", len(existing_set))

    # Filter out files already in Qdrant before starting threads
    to_process = [p for p in downloaded_files if p.name not in existing_set]
    logger.info("Total remaining PDFs to process: %d (Skipped %d already ingested).", len(to_process), len(downloaded_files) - len(to_process))

    if not to_process:
        logger.info("All PDFs are already ingested! Ingestion complete.")
        return

    from concurrent.futures import ThreadPoolExecutor, as_completed

    ingested_count = 0
    skipped_count = 0
    error_count = 0
    total_chunks = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_single_pdf, pdf_path, client, existing_set): pdf_path
            for pdf_path in to_process
        }

        for future in as_completed(futures):
            status, chunks = future.result()
            if status == "ingested":
                ingested_count += 1
                total_chunks += chunks
            elif status == "skipped":
                skipped_count += 1
            elif status == "error":
                error_count += 1

    logger.info(
        "Ingestion summary complete! Ingested: %d cases (%d vector chunks) | Skipped non-criminal/empty: %d | Errors: %d",
        ingested_count, total_chunks, skipped_count, error_count
    )


async def main():
    scrape_only = "--scrape-only" in sys.argv
    ingest_only = "--ingest-only" in sys.argv or "--no-scrape" in sys.argv

    # Parse --years argument
    if "--years" in sys.argv:
        idx = sys.argv.index("--years")
        years = []
        for val in sys.argv[idx + 1:]:
            if val.startswith("--"):
                break
            try:
                years.append(int(val))
            except ValueError:
                pass
    else:
        years = [2024, 2025, 2026]

    logger.info("Target years: %s | Scrape-only: %s | Ingest-only: %s", years, scrape_only, ingest_only)
    logger.info("Connecting to Qdrant Cloud...")
    client = get_qdrant_client()
    ensure_collections(client)
    
    if ingest_only:
        logger.info("Ingest-only mode enabled. Skipping Web API scraper...")
        existing_files = []
        for y in years:
            existing_files.extend(list(Path("downloads").glob(f"{y}_IHC_*.pdf")))
        logger.info("Found %d downloaded IHC PDFs for years %s. Starting ingestion...", len(existing_files), years)
        ingest_downloaded_files(existing_files, client)
        return

    all_downloaded = []
    for year in years:
        try:
            downloaded = await scrape_year(year)
            all_downloaded.extend(downloaded)
        except Exception as exc:
            logger.error("Failed scraping for year %d: %s", year, exc, exc_info=True)
            
    if scrape_only:
        logger.info("Scrape-only mode active. Total PDFs downloaded: %d. Exiting without ingestion.", len(all_downloaded))
        return

    if all_downloaded:
        ingest_downloaded_files(all_downloaded, client)
    else:
        existing = list(Path("downloads").glob("*_IHC_*.pdf"))
        if existing:
            logger.info("Found %d existing IHC PDFs in downloads directory. Starting ingestion...", len(existing))
            ingest_downloaded_files(existing, client)

if __name__ == "__main__":
    asyncio.run(main())
