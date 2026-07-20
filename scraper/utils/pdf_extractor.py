"""
pdf_extractor.py — Extract raw text from PDF files using pdfplumber.

Usage:
    from scraper.utils.pdf_extractor import extract_text_from_pdf
    text, metadata = extract_text_from_pdf(Path("judgment.pdf"))
"""

import logging
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)


def extract_text_from_pdf(pdf_path: Path) -> tuple:
    """
    Extract full text and basic metadata from a PDF file.

    Args:
        pdf_path: Absolute or relative path to the PDF file.

    Returns:
        A tuple of:
          - full_text (str): All pages concatenated with page-break markers.
          - metadata (dict): Keys: num_pages, file_name, file_size_kb.

    Raises:
        FileNotFoundError: If the PDF does not exist.
        ValueError: If the PDF yields no extractable text (scanned image, etc.).
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    logger.info("Extracting text from: %s", pdf_path.name)

    pages_text = []

    with pdfplumber.open(pdf_path) as pdf:
        num_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(x_tolerance=2, y_tolerance=2)
            if text:
                pages_text.append(f"[PAGE {i}]\n{text.strip()}")
            else:
                logger.debug("Page %d/%d had no extractable text.", i, num_pages)

    full_text = "\n\n".join(pages_text)

    if not full_text.strip():
        raise ValueError(
            f"No text extracted from {pdf_path.name}. "
            "The PDF may be a scanned image — consider OCR preprocessing."
        )

    metadata = {
        "num_pages": num_pages,
        "file_name": pdf_path.name,
        "file_size_kb": round(pdf_path.stat().st_size / 1024, 2),
    }

    logger.info(
        "Extracted %d chars from %d page(s) of %s",
        len(full_text), num_pages, pdf_path.name,
    )
    return full_text, metadata
