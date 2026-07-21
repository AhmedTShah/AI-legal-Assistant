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


_ocr_reader = None


def _get_ocr_reader():
    """Lazily load the EasyOCR reader to avoid importing it when not needed."""
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        logger.info("Initializing EasyOCR reader (English)...")
        # EasyOCR automatically detects and uses CUDA if available.
        # verbose=False disables progress prints to avoid Windows codec errors.
        _ocr_reader = easyocr.Reader(['en'], verbose=False)
    return _ocr_reader


def _ocr_page(pdf_path: Path, page_index: int) -> str:
    """Render a PDF page as an image using pypdfium2 and extract text with EasyOCR."""
    import pypdfium2 as pdfium
    import numpy as np
    try:
        doc = pdfium.PdfDocument(str(pdf_path))
        page = doc[page_index]
        bitmap = page.render(scale=2)  # Scale=2 increases OCR accuracy
        pil_img = bitmap.to_pil()
        doc.close()

        # Convert PIL image to a numpy array for EasyOCR
        img_arr = np.array(pil_img)

        reader = _get_ocr_reader()
        results = reader.readtext(img_arr, detail=0)
        return "\n".join(results)
    except Exception as exc:
        logger.error("OCR failed for page %d: %s", page_index + 1, exc)
        return ""


def extract_text_from_pdf(pdf_path: Path) -> tuple:
    """
    Extract full text and basic metadata from a PDF file.
    Uses pdfplumber for digital text, and falls back to EasyOCR for scanned pages.

    Args:
        pdf_path: Absolute or relative path to the PDF file.

    Returns:
        A tuple of:
          - full_text (str): All pages concatenated with page-break markers.
          - metadata (dict): Keys: num_pages, file_name, file_size_kb.

    Raises:
        FileNotFoundError: If the PDF does not exist.
        ValueError: If the PDF yields no extractable text even after OCR.
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
            if text and text.strip():
                pages_text.append(f"[PAGE {i}]\n{text.strip()}")
            else:
                logger.info("Page %d/%d has no digital text. Falling back to OCR...", i, num_pages)
                ocr_text = _ocr_page(pdf_path, i - 1)
                if ocr_text.strip():
                    pages_text.append(f"[PAGE {i} - OCR]\n{ocr_text.strip()}")
                else:
                    logger.warning("No text could be extracted from page %d (even with OCR).", i)

    full_text = "\n\n".join(pages_text)

    if not full_text.strip():
        raise ValueError(
            f"No text extracted from {pdf_path.name} (digital extraction and OCR both returned empty)."
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
