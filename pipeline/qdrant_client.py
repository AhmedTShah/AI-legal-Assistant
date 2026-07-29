"""
qdrant_client.py — Qdrant connection manager and collection bootstrap.

Reads QDRANT_URL and QDRANT_API_KEY from the environment (loaded via .env).

Usage:
    from pipeline.qdrant_client import get_qdrant_client, ensure_collections
    client = get_qdrant_client()
    ensure_collections(client)
"""

import logging
import os

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

load_dotenv()

logger = logging.getLogger(__name__)

# ── Collection definitions ─────────────────────────────────────────────────────
VECTOR_SIZE     = 768                          # Gemini text-embedding-004
DISTANCE_METRIC = qmodels.Distance.COSINE

COLLECTIONS = {
    "precedents_db": {
        "description": "Supreme Court + High Court judgment chunks",
        "vector_size": VECTOR_SIZE,
        "distance": DISTANCE_METRIC,
    },
    "user_misl_db": {
        "description": "User-uploaded case docs: FIRs, witness statements, depositions",
        "vector_size": VECTOR_SIZE,
        "distance": DISTANCE_METRIC,
    },
    # NOTE: statutes_db is managed by the partner — do NOT create or touch it here.
}


def get_qdrant_client() -> QdrantClient:
    """
    Create and return a Qdrant client using env vars.

    Raises:
        EnvironmentError: If QDRANT_URL or QDRANT_API_KEY are missing.
        ConnectionError:  If the Qdrant instance cannot be reached.
    """
    url = os.getenv("QDRANT_URL")
    api_key = os.getenv("QDRANT_API_KEY")

    if not url:
        raise EnvironmentError("QDRANT_URL is not set. Check your .env file.")
    if not api_key:
        raise EnvironmentError("QDRANT_API_KEY is not set. Check your .env file.")

    logger.info("Connecting to Qdrant at %s ...", url)

    client = QdrantClient(url=url, api_key=api_key, timeout=30)

    # ── Verify connectivity ───────────────────────────────────────────────
    try:
        info = client.get_collections()
        existing = [c.name for c in info.collections]
        logger.info(
            "Qdrant connection OK — %d collection(s) found: %s",
            len(existing), existing or "[]",
        )
    except Exception as exc:
        raise ConnectionError(
            f"Failed to connect to Qdrant at {url}: {exc}"
        ) from exc

    return client


def ensure_collections(client: QdrantClient) -> None:
    """
    Create precedents_db and user_misl_db if they don't already exist.
    Safe to call repeatedly — existing collections are untouched.

    Args:
        client: A connected QdrantClient instance.
    """
    existing = {c.name for c in client.get_collections().collections}

    for name, config in COLLECTIONS.items():
        if name in existing:
            logger.info("Collection '%s' already exists — skipping creation.", name)
            continue

        logger.info("Creating collection '%s' ...", name)
        client.create_collection(
            collection_name=name,
            vectors_config=qmodels.VectorParams(
                size=config["vector_size"],
                distance=config["distance"],
            ),
        )
        logger.info("Collection '%s' created (size=%d, metric=COSINE).", name, config["vector_size"])

    # Ensure payload indexes exist for filtering fields
    indexes = {
        "file_name": qmodels.PayloadSchemaType.KEYWORD,
        "court": qmodels.PayloadSchemaType.KEYWORD,
        "year": qmodels.PayloadSchemaType.INTEGER,
        "case_type": qmodels.PayloadSchemaType.KEYWORD,
        "laws_cited": qmodels.PayloadSchemaType.KEYWORD
    }
    
    for name in COLLECTIONS.keys():
        for field, schema in indexes.items():
            try:
                logger.info("Ensuring payload index on '%s.%s' exists...", name, field)
                client.create_payload_index(
                    collection_name=name,
                    field_name=field,
                    field_schema=schema
                )
            except Exception as exc:
                # Sometimes fails if index already exists
                logger.debug("Index creation issue on %s.%s: %s", name, field, exc)

    logger.info("Collection bootstrap complete.")


def delete_collection(client: QdrantClient, name: str) -> None:
    """
    Utility: Delete a collection by name. Use with caution.
    Will not delete statutes_db (partner-managed collection).
    """
    if name == "statutes_db":
        raise PermissionError(
            "Refusing to delete 'statutes_db' — this is managed by the partner."
        )
    client.delete_collection(name)
    logger.warning("Deleted collection '%s'.", name)
