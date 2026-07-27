"""
embedder.py — Generate Google Gemini embeddings with intelligent key rotation, monthly quota exclusion, and failover.
"""

import logging
import os
import threading
import time
from typing import Optional

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
EMBEDDING_MODEL  = "models/gemini-embedding-001"
EMBEDDING_DIM    = 768
BATCH_SIZE       = 100
RATE_LIMIT_SLEEP = 2.5


class KeyManager:
    """Thread-safe API Key Rotator with automatic exclusion of exhausted keys."""
    def __init__(self):
        self._lock = threading.Lock()
        raw_keys = os.getenv("GEMINI_API_KEYS", "")
        all_keys = [k.strip() for k in raw_keys.split(",") if k.strip()] if raw_keys else []
        if not all_keys:
            single_key = os.getenv("GEMINI_API_KEY", "")
            if single_key:
                all_keys = [single_key.strip()]

        if not all_keys:
            raise EnvironmentError("No GEMINI_API_KEY or GEMINI_API_KEYS found in environment.")

        self.keys = all_keys
        self.exhausted_keys = set()
        self.index = 0
        logger.info("Initialized Gemini KeyManager with %d API key(s).", len(self.keys))

    def get_current_key(self) -> str:
        with self._lock:
            active_keys = [k for k in self.keys if k not in self.exhausted_keys]
            if not active_keys:
                raise RuntimeError("All Gemini API keys have exceeded their monthly spending caps!")
            return active_keys[self.index % len(active_keys)]

    def rotate_key(self) -> str:
        with self._lock:
            active_keys = [k for k in self.keys if k not in self.exhausted_keys]
            if not active_keys:
                raise RuntimeError("All Gemini API keys have exceeded their monthly spending caps!")
            self.index = (self.index + 1) % len(active_keys)
            next_key = active_keys[self.index]
            logger.info("Rotated to active Gemini API key #%d/%d (ends in ...%s)", self.index + 1, len(active_keys), next_key[-6:])
            return next_key

    def mark_exhausted(self, key: str):
        with self._lock:
            if key not in self.exhausted_keys:
                self.exhausted_keys.add(key)
                logger.warning("Permanently disabled exhausted key (ends in ...%s). %d active key(s) remaining.", key[-6:], len(self.keys) - len(self.exhausted_keys))


_key_manager = None


def _get_key_manager() -> KeyManager:
    global _key_manager
    if _key_manager is None:
        _key_manager = KeyManager()
    return _key_manager


def embed_texts(
    texts: list,
    model: str = EMBEDDING_MODEL,
    task_type: str = "RETRIEVAL_DOCUMENT",
    output_dimensionality: Optional[int] = EMBEDDING_DIM,
) -> list:
    """
    Generate Gemini embeddings for a list of raw text strings using multi-key rotation.
    """
    texts = [t.strip() for t in texts if t and isinstance(t, str) and t.strip()]
    if not texts:
        return []

    km = _get_key_manager()
    all_embeddings = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        logger.info(
            "Embedding batch %d-%d / %d ...",
            i + 1, min(i + BATCH_SIZE, len(texts)), len(texts),
        )
        
        attempts = 0
        max_attempts = 15

        while attempts < max_attempts:
            current_key = km.rotate_key()
            genai.configure(api_key=current_key)
            try:
                result = genai.embed_content(
                    model=model,
                    content=batch,
                    task_type=task_type,
                    output_dimensionality=output_dimensionality,
                )
                vectors = result["embedding"]
                all_embeddings.extend(vectors)
                time.sleep(4.0)
                break
            except Exception as exc:
                attempts += 1
                error_str = str(exc).lower()
                if "spend" in error_str or "monthly" in error_str:
                    logger.warning("Key (ends in ...%s) exceeded monthly spend cap. Removing from pool...", current_key[-6:])
                    km.mark_exhausted(current_key)
                    time.sleep(1.0)
                elif any(term in error_str for term in ["quota", "rate", "429", "resourceexhausted"]):
                    logger.warning(
                        "Per-minute rate limit hit on key (ends in ...%s). Rotating & sleeping 10s (attempt %d/%d)...",
                        current_key[-6:],
                        attempts,
                        max_attempts
                    )
                    km.rotate_key()
                    time.sleep(10.0)
                else:
                    logger.error("Gemini embedding error: %s", exc)
                    raise

    logger.info("Generated %d embedding(s).", len(all_embeddings))
    return all_embeddings


def embed_chunks(
    chunks: list,
    model: str = EMBEDDING_MODEL,
    task_type: str = "RETRIEVAL_DOCUMENT",
    output_dimensionality: Optional[int] = EMBEDDING_DIM,
) -> list:
    """
    Add an 'embedding' field to each chunk dict in-place.
    """
    texts = [c["text"] for c in chunks]
    vectors = embed_texts(
        texts,
        model=model,
        task_type=task_type,
        output_dimensionality=output_dimensionality,
    )

    for chunk, vector in zip(chunks, vectors):
        chunk["embedding"] = vector

    return chunks
