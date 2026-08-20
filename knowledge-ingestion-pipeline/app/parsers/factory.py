from __future__ import annotations

from pathlib import Path

from app.parsers.base import Parser
from app.parsers.docx import DocxParser
from app.parsers.pdf import PdfParser
from app.parsers.text import TextParser
from app.parsers.xlsx import XlsxParser

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".md", ".markdown", ".txt"}


def get_parser(
    path: Path,
    pdf_ocr_min_chars_per_page: int = 30,
    pdf_primary_engine: str = "pdfium",
    pdf_quality_threshold: float = 0.65,
) -> Parser:
    extension = path.suffix.lower()
    if extension == ".pdf":
        return PdfParser(
            min_chars_per_page=pdf_ocr_min_chars_per_page,
            primary_engine=pdf_primary_engine,
            quality_threshold=pdf_quality_threshold,
        )
    if extension == ".docx":
        return DocxParser()
    if extension == ".xlsx":
        return XlsxParser()
    if extension in {".md", ".markdown"}:
        return TextParser(markdown=True)
    if extension == ".txt":
        return TextParser()
    raise ValueError(f"Unsupported file type: {extension or '<none>'}")
