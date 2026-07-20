"""
ingest_misl.py — Ingest user-uploaded case documents into user_misl_db.

Supported document types: FIRs, witness statements, depositions, bail applications.

Pipeline:
    Uploaded file -> text extraction -> chunking -> embedding -> Qdrant upsert

Usage:
    python -m pipeline.ingest_misl \\
        --file uploads/fir_12345.pdf \\
        --doc-type FIR \\
        --case-number 123/2024 \\
        --uploaded-by user@example.com

    # Process all files in uploads/:
    python -m pipeline.ingest_misl --dir uploads/
"""

import argparse
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

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
logger = logging.getLogger("ingest_misl")

COLLECTION_NAME = "user_misl_db"
CHUNK_SIZE      = 500
CHUNK_OVERLAP   = 50
UPSERT_BATCH    = 64

VALID_DOC_TYPES = {
    "FIR", "WITNESS_STATEMENT", "DEPOSITION",
    "BAIL_APPLICATION", "CHARGE_SHEET", "OTHER",
}


def ingest_document(
    file_path: Path,
    client: QdrantClient,
    doc_type: str = "OTHER",
    case_number: str = "",
    uploaded_by: str = "",
    notes: str = "",
) -> int:
    """
    Ingest a single user-uploaded case document into user_misl_db.

    Args:
        file_path   : Path to the uploaded PDF.
        client      : Connected QdrantClient.
        doc_type    : Document category (FIR, WITNESS_STATEMENT, etc.).
        case_number : Court case reference number.
        uploaded_by : Identifier of the user who uploaded the file.
        notes       : Any free-text notes about the document.

    Returns:
        Number of chunks uploaded.
    """
    file_path = Path(file_path)
    doc_type  = doc_type.upper().replace(" ", "_")
    if doc_type not in VALID_DOC_TYPES:
        logger.warning("Unknown doc_type '%s' — falling back to 'OTHER'.", doc_type)
        doc_type = "OTHER"

    logger.info("Ingesting user document: %s (type=%s)", file_path.name, doc_type)

    # 1. Extract text
    full_text, pdf_meta = extract_text_from_pdf(file_path)

    # 2. Chunk
    chunks = chunk_text(full_text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
    if not chunks:
        logger.warning("No chunks from %s — skipping.", file_path.name)
        return 0

    # 3. Embed
    chunks = embed_chunks(chunks)

    # 4. Build points
    upload_ts = datetime.now(tz=timezone.utc).isoformat()
    points: list[qmodels.PointStruct] = []

    for chunk in chunks:
        payload = {
            "doc_type"   : doc_type,
            "case_number": case_number,
            "uploaded_by": uploaded_by,
            "notes"      : notes,
            "file_name"  : file_path.name,
            "uploaded_at": upload_ts,
            "chunk_index": chunk["chunk_index"],
            "token_count": chunk["token_count"],
            "text"       : chunk["text"],
        }
        points.append(
            qmodels.PointStruct(
                id=str(uuid.uuid4()),
                vector=chunk["embedding"],
                payload=payload,
            )
        )

    # 5. Upsert
    total_uploaded = 0
    for i in range(0, len(points), UPSERT_BATCH):
        batch = points[i : i + UPSERT_BATCH]
        client.upsert(collection_name=COLLECTION_NAME, points=batch)
        total_uploaded += len(batch)
        logger.info("Upserted %d/%d chunks ...", min(i + UPSERT_BATCH, len(points)), len(points))

    logger.info(
        "%s — %d chunks uploaded to '%s'.",
        file_path.name, total_uploaded, COLLECTION_NAME,
    )
    return total_uploaded


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest user-uploaded case documents into user_misl_db"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", type=Path, help="Single document to ingest")
    group.add_argument("--dir",  type=Path, help="Directory of documents to ingest")

    parser.add_argument(
        "--doc-type", default="OTHER",
        choices=list(VALID_DOC_TYPES),
        help="Document category",
    )
    parser.add_argument("--case-number",  default="", help="Court case reference number")
    parser.add_argument("--uploaded-by",  default="", help="User identifier")
    parser.add_argument("--notes",        default="", help="Free-text notes")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    client = get_qdrant_client()
    ensure_collections(client)

    files: list[Path] = []
    if args.file:
        files = [args.file]
    elif args.dir:
        files = sorted(args.dir.glob("*.pdf"))
        logger.info("Found %d PDF(s) in %s", len(files), args.dir)

    total = 0
    for f in files:
        try:
            total += ingest_document(
                file_path=f,
                client=client,
                doc_type=args.doc_type,
                case_number=args.case_number,
                uploaded_by=args.uploaded_by,
                notes=args.notes,
            )
        except Exception as exc:
            logger.error("Failed to ingest %s: %s", f.name, exc, exc_info=True)

    print(f"\nIngestion complete — {total} total chunks uploaded to '{COLLECTION_NAME}'.")


if __name__ == "__main__":
    main()
