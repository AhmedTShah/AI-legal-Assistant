"""
chunker.py — Split judgment text into overlapping token-aware chunks.

Uses tiktoken to count tokens accurately so chunk sizes reflect what
OpenAI embedding models actually see.

Usage:
    from scraper.utils.chunker import chunk_text
    chunks = chunk_text(text, chunk_size=500, overlap=50)
"""

import logging
import re
from typing import Optional

import tiktoken

logger = logging.getLogger(__name__)

_DEFAULT_ENCODING = "cl100k_base"


def _get_encoder(encoding_name: str = _DEFAULT_ENCODING) -> tiktoken.Encoding:
    return tiktoken.get_encoding(encoding_name)


def chunk_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
    encoding_name: str = _DEFAULT_ENCODING,
    separator: Optional[str] = None,
) -> list:
    """
    Split text into overlapping chunks measured in tokens.

    Args:
        text          : The full document text to split.
        chunk_size    : Maximum tokens per chunk (default 500).
        overlap       : Tokens of overlap between consecutive chunks (default 50).
        encoding_name : tiktoken encoding (default cl100k_base).
        separator     : Optional regex pattern to prefer splitting at natural
                        boundaries (e.g. r'\\n\\n' for paragraphs).

    Returns:
        List of dicts: [{"chunk_index": int, "text": str, "token_count": int}]
    """
    if not text or not text.strip():
        logger.warning("chunk_text received empty input — returning []")
        return []

    enc = _get_encoder(encoding_name)

    # Optional paragraph-aware pre-splitting
    if separator:
        segments = [s.strip() for s in re.split(separator, text) if s.strip()]
    else:
        segments = [text]

    # Tokenise all segments
    all_tokens = []
    for seg in segments:
        all_tokens.extend(enc.encode(seg))
        all_tokens.extend(enc.encode(" "))

    # Sliding-window chunking
    chunks = []
    start = 0
    chunk_idx = 0

    while start < len(all_tokens):
        end = min(start + chunk_size, len(all_tokens))
        token_slice = all_tokens[start:end]
        chunk_text_str = enc.decode(token_slice)

        chunks.append({
            "chunk_index": chunk_idx,
            "text": chunk_text_str.strip(),
            "token_count": len(token_slice),
        })

        chunk_idx += 1
        next_start = start + chunk_size - overlap
        if next_start <= start:
            next_start = start + 1
        start = next_start

    logger.info(
        "Chunked text into %d chunks (size=%d, overlap=%d tokens).",
        len(chunks), chunk_size, overlap,
    )
    return chunks
