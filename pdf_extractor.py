"""PDF text extraction via PyMuPDF."""

import fitz  # PyMuPDF
from pathlib import Path

from utils import clean_text


def extract_text(pdf_path: Path, password: str | None = None) -> str:
    """Extract all text from a PDF file (optionally password-protected)."""
    doc = fitz.open(str(pdf_path))
    if doc.is_encrypted and password:
        doc.authenticate(password)
    parts: list[str] = []
    for page in doc:
        text = page.get_text()
        if text:
            parts.append(text)
    return clean_text("\n".join(parts))


def save_and_extract(pdf_path: Path, password: str | None = None) -> str:
    """Ensure file exists then extract text."""
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    return extract_text(pdf_path, password=password)
