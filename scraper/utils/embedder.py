"""
embedder.py — Generate Google Gemini embeddings for text chunks.

Uses gemini-embedding-exp-03-07 (3072-dim output, truncated to 768 here)
OR text-embedding-004 (768-dim) — both work with Qdrant collections.

NOTE: Our Qdrant collections use vector size 768 when using Gemini.
      If you already created collections with size 1536 (OpenAI), you must
      recreate them with size 768 before ingesting.

Usage:
    from scraper.utils.embedder import embed_chunks
    chunks = embed_chunks(chunks)   # chunks = list of {"text": str, ...}
"""

import logging
import os
import time
from typing import Optional

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
# text-embedding-004 produces 768-dim vectors (stable, production-ready)
EMBEDDING_MODEL  = "models/text-embedding-004"
EMBEDDING_DIM    = 768      # update qdrant_client.py VECTOR_SIZE to match
BATCH_SIZE       = 100      # Gemini supports up to 100 texts per batch call
RATE_LIMIT_SLEEP = 1.0      # seconds between batches


def _configure_genai() -> None:
    """Configure the Gemini SDK with the API key from environment."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY not set. Add it to your .env file."
        )
    genai.configure(api_key=api_key)


def embed_texts(
    texts: list,
    model: str = EMBEDDING_MODEL,
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list:
    """
    Generate Gemini embeddings for a list of raw text strings.

    Args:
        texts     : List of strings to embed.
        model     : Gemini embedding model name.
        task_type : One of RETRIEVAL_DOCUMENT, RETRIEVAL_QUERY, SEMANTIC_SIMILARITY.
                    Use RETRIEVAL_DOCUMENT when ingesting; RETRIEVAL_QUERY when searching.

    Returns:
        List of embedding vectors (each a list of 768 floats).
    """
    if not texts:
        return []

    _configure_genai()
    all_embeddings = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        logger.info(
            "Embedding batch %d-%d / %d ...",
            i + 1, min(i + BATCH_SIZE, len(texts)), len(texts),
        )
        try:
            result = genai.embed_content(
                model=model,
                content=batch,
                task_type=task_type,
            )
            # result["embedding"] is a list of vectors when content is a list
            vectors = result["embedding"]
            all_embeddings.extend(vectors)

            if i + BATCH_SIZE < len(texts):
                time.sleep(RATE_LIMIT_SLEEP)

        except Exception as exc:
            error_str = str(exc).lower()
            if "quota" in error_str or "rate" in error_str or "429" in error_str:
                logger.warning("Rate limit hit — sleeping 60 s before retrying ...")
                time.sleep(60)
                # Retry this batch once
                result = genai.embed_content(
                    model=model,
                    content=batch,
                    task_type=task_type,
                )
                all_embeddings.extend(result["embedding"])
            else:
                logger.error("Gemini embedding error: %s", exc)
                raise

    logger.info("Generated %d embedding(s).", len(all_embeddings))
    return all_embeddings


def embed_chunks(
    chunks: list,
    model: str = EMBEDDING_MODEL,
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list:
    """
    Add an 'embedding' field to each chunk dict in-place.

    Args:
        chunks    : List of chunk dicts (must have a 'text' key).
        model     : Gemini embedding model name.
        task_type : Embedding task type.

    Returns:
        The same list with each dict enriched with an 'embedding' key.
    """
    texts = [c["text"] for c in chunks]
    vectors = embed_texts(texts, model=model, task_type=task_type)

    for chunk, vector in zip(chunks, vectors):
        chunk["embedding"] = vector

    return chunks
