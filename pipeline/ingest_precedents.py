"""
ingest_precedents.py — Ingest court judgment PDFs into the precedents_db Qdrant collection.

Pipeline:
    PDF file -> text extraction -> chunking -> embedding -> Qdrant upsert

Usage:
    python -m pipeline.ingest_precedents \\
        --pdf downloads/judgment_xyz.pdf \\
        --court LHC \\
        --year 2023 \\
        --source-url https://www.lhc.gov.pk/case-law/judgment/12345 \\
        --laws-cited PECA,PPC \\
        --case-type cybercrime

    # Or process an entire directory:
    python -m pipeline.ingest_precedents --dir downloads/ --court LHC
"""

import argparse
import logging
import re
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from pipeline.qdrant_client import get_qdrant_client, ensure_collections
from scraper.utils.pdf_extractor import extract_text_from_pdf
from scraper.utils.chunker import chunk_text
from scraper.utils.embedder import embed_chunks

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ingest_precedents")

COLLECTION_NAME = "precedents_db"
CHUNK_SIZE      = 500   # tokens
CHUNK_OVERLAP   = 50    # tokens
UPSERT_BATCH    = 64    # points per Qdrant upsert call


def _guess_year(filename: str) -> Optional[int]:
    """Try to extract a 4-digit year from a filename."""
    match = re.search(r"(19|20)\d{2}", filename)
    return int(match.group()) if match else None


def ingest_pdf(
    pdf_path: Path,
    client: QdrantClient,
    court: str,
    year: Optional[int] = None,
    source_url: str = "",
    laws_cited: Optional[list] = None,
    case_type: str = "",
) -> int:
    """
    Full ingestion pipeline for a single PDF judgment.

    Args:
        pdf_path   : Path to the downloaded PDF.
        client     : Connected QdrantClient.
        court      : Court identifier (e.g. "LHC", "SCP").
        year       : Judgment year (extracted from filename if not provided).
        source_url : Original URL the PDF was downloaded from.
        laws_cited : List of law names cited in the judgment.
        case_type  : Category (e.g. "cybercrime", "defamation").

    Returns:
        Number of chunks uploaded.
    """
    pdf_path = Path(pdf_path)
    logger.info("Ingesting: %s", pdf_path.name)

    # 1. Extract text
    full_text, pdf_meta = extract_text_from_pdf(pdf_path)

    # 2. Chunk
    chunks = chunk_text(full_text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
    if not chunks:
        logger.warning("No chunks produced for %s — skipping.", pdf_path.name)
        return 0

    # 3. Embed
    chunks = embed_chunks(chunks)

    # 4. Build Qdrant points with metadata
    points: list[qmodels.PointStruct] = []
    for chunk in chunks:
        payload = {
            # Required metadata fields per spec
            "court"      : court,
            "year"       : year or _guess_year(pdf_path.name),
            "source_url" : source_url or (
                f"https://sys.lhc.gov.pk/appjudgments/{pdf_path.name}" if court == "LHC" 
                else (f"https://caselaw.shc.gov.pk/caselaw/view-file/{pdf_path.stem.split('_SHC_')[-1]}" if court == "SHC" and "_SHC_" in pdf_path.name 
                else "")
            ),
            "laws_cited" : laws_cited or [],
            "case_type"  : case_type,
            # Provenance
            "file_name"  : pdf_path.name,
            "chunk_index": chunk["chunk_index"],
            "token_count": chunk["token_count"],
            # Full chunk text (for retrieval / display)
            "text"       : chunk["text"],
        }
        points.append(
            qmodels.PointStruct(
                id=str(uuid.uuid4()),
                vector=chunk["embedding"],
                payload=payload,
            )
        )

    # 5. Upsert in batches
    total_uploaded = 0
    for i in range(0, len(points), UPSERT_BATCH):
        batch = points[i : i + UPSERT_BATCH]
        client.upsert(collection_name=COLLECTION_NAME, points=batch)
        total_uploaded += len(batch)
        logger.info(
            "Upserted batch %d-%d / %d chunks ...",
            i + 1, min(i + UPSERT_BATCH, len(points)), len(points),
        )

    logger.info(
        "%s — %d chunks uploaded to '%s'.",
        pdf_path.name, total_uploaded, COLLECTION_NAME,
    )
    return total_uploaded


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest court judgment PDFs into precedents_db"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pdf", type=Path, help="Single PDF file to ingest")
    group.add_argument("--dir", type=Path, help="Directory of PDFs to ingest")

    parser.add_argument("--court",      required=True, help="Court code (e.g. LHC, SCP)")
    parser.add_argument("--year",       type=int,      default=None, help="Judgment year")
    parser.add_argument("--source-url", default="",    help="Source URL of the judgment PDF")
    parser.add_argument("--laws-cited", default="",    help="Comma-separated list of laws cited")
    parser.add_argument("--case-type",  default="",    help="Case category (e.g. cybercrime)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    laws = [l.strip() for l in args.laws_cited.split(",") if l.strip()]

    client = get_qdrant_client()
    ensure_collections(client)

    pdfs: list[Path] = []
    if args.pdf:
        pdfs = [args.pdf]
    elif args.dir:
        all_pdfs = sorted(args.dir.glob("*.pdf"))
        court_filter = args.court.upper()
        pdfs = [p for p in all_pdfs if court_filter in p.name.upper()]
        logger.info("Found %d PDF(s) matching court '%s' in %s", len(pdfs), court_filter, args.dir)

    total = 0
    for pdf in pdfs:
        # Check if this file has already been ingested into Qdrant to prevent duplicates
        try:
            existing = client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="file_name",
                            match=qmodels.MatchValue(value=pdf.name)
                        )
                    ]
                ),
                limit=1,
                with_payload=False,
                with_vectors=False
            )
            if existing[0]:
                logger.info("PDF %s is already ingested — skipping.", pdf.name)
                continue
        except Exception as exc:
            logger.warning("Could not check duplicate status for %s: %s", pdf.name, exc)

        try:
            total += ingest_pdf(
                pdf_path=pdf,
                client=client,
                court=args.court.upper(),
                year=args.year,
                source_url=args.source_url,
                laws_cited=laws,
                case_type=args.case_type,
            )
        except Exception as exc:
            logger.error("Failed to ingest %s: %s", pdf.name, exc, exc_info=True)

    print(f"\nIngestion complete — {total} total chunks uploaded to '{COLLECTION_NAME}'.")


if __name__ == "__main__":
    main()
