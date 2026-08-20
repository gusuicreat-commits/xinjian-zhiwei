from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pypdfium2 as pdfium
from pypdf import PdfReader

from app.models import Document
from app.parsers.base import Parser


class PdfParser(Parser):
    def __init__(
        self,
        min_chars_per_page: int = 30,
        primary_engine: str = "pdfium",
        quality_threshold: float = 0.65,
    ) -> None:
        if primary_engine not in {"pdfium", "pypdf"}:
            raise ValueError("primary_engine must be 'pdfium' or 'pypdf'")
        if not 0 <= quality_threshold <= 1:
            raise ValueError("quality_threshold must be between 0 and 1")
        self.min_chars_per_page = min_chars_per_page
        self.primary_engine = primary_engine
        self.quality_threshold = quality_threshold

    def parse(self, path: Path) -> List[Document]:
        reader = PdfReader(str(path))
        pdfium_document = pdfium.PdfDocument(str(path))
        base = {
            **self.base_metadata(path, "pdf"),
            "page_count": len(reader.pages),
        }
        documents: List[Document] = []
        current_section: Optional[str] = None
        try:
            for index, pypdf_page in enumerate(reader.pages):
                text, method, quality = self._extract_best(pypdf_page, pdfium_document, index)
                font_mapping_missing = self._font_mapping_missing(pypdf_page)
                visible_chars = sum(not char.isspace() for char in text)
                ocr_required = (
                    visible_chars < self.min_chars_per_page or quality < self.quality_threshold
                )
                inferred = self._infer_heading(text)
                if inferred:
                    current_section = inferred
                metadata = {
                    **base,
                    "page": index + 1,
                    "extraction_method": method,
                    "text_quality_score": round(quality, 4),
                    "font_mapping_missing": font_mapping_missing,
                    "ocr_required": ocr_required,
                }
                if ocr_required:
                    metadata["ocr_reason"] = (
                        "insufficient_text"
                        if visible_chars < self.min_chars_per_page
                        else "native_text_quality_failed"
                    )
                if current_section:
                    metadata["section"] = current_section
                documents.append(Document(content=text, metadata=metadata))
        finally:
            pdfium_document.close()
        return documents

    def _extract_best(self, pypdf_page, pdfium_document, index: int) -> Tuple[str, str, float]:
        candidates: List[Tuple[str, str, float]] = []
        engines = [self.primary_engine]
        if self.primary_engine == "pdfium":
            engines.append("pypdf")
        else:
            engines.append("pdfium")

        for engine in engines:
            try:
                if engine == "pdfium":
                    page = pdfium_document[index]
                    text_page = page.get_textpage()
                    try:
                        text = text_page.get_text_bounded().strip()
                    finally:
                        text_page.close()
                        page.close()
                else:
                    text = (pypdf_page.extract_text() or "").strip()
            except Exception:
                continue
            quality = score_text_quality(text)
            candidates.append((text, engine, quality))
            if engine == self.primary_engine and quality >= self.quality_threshold:
                return candidates[-1]

        if not candidates:
            return "", "none", 0.0
        return max(candidates, key=lambda candidate: (candidate[2], len(candidate[0])))

    @staticmethod
    def _font_mapping_missing(page) -> bool:
        try:
            fonts = page["/Resources"].get("/Font", {})
            for reference in fonts.values():
                font = reference.get_object()
                if font.get("/Subtype") == "/Type0" and "/ToUnicode" not in font:
                    return True
        except Exception:
            return False
        return False

    @staticmethod
    def _infer_heading(text: str) -> Optional[str]:
        for line in text.splitlines()[:5]:
            candidate = line.strip()
            if not candidate or len(candidate) > 100:
                continue
            if re.match(r"^(?:\d+(?:\.\d+)*\s+|第.+[章节]\s*)\S+", candidate):
                return candidate
        return None


def score_text_quality(text: str) -> float:
    """Estimate extraction quality without rewriting or interpreting source text."""
    visible = [char for char in text if not char.isspace()]
    if not visible:
        return 0.0

    printable_ratio = sum(char.isprintable() for char in visible) / len(visible)
    replacement_ratio = sum(char in {"\ufffd", "\x00"} for char in visible) / len(visible)
    alnum_ratio = sum(char.isalnum() for char in visible) / len(visible)

    scripts: Dict[str, int] = {}
    letters = 0
    for char in visible:
        if not char.isalpha():
            continue
        letters += 1
        script = _script_name(char)
        scripts[script] = scripts.get(script, 0) + 1
    dominant_scripts = sum(sorted(scripts.values(), reverse=True)[:2])
    script_consistency = dominant_scripts / letters if letters else 1.0
    fragmentation_penalty = min(max(len(scripts) - 3, 0) * 0.06, 0.3)

    score = (
        0.35 * printable_ratio
        + 0.25 * min(alnum_ratio / 0.65, 1.0)
        + 0.4 * script_consistency
        - replacement_ratio * 2
        - fragmentation_penalty
    )
    return max(0.0, min(score, 1.0))


def _script_name(char: str) -> str:
    codepoint = ord(char)
    if 0x3400 <= codepoint <= 0x9FFF or 0xF900 <= codepoint <= 0xFAFF:
        return "CJK"
    if char.isascii():
        return "LATIN"
    name = unicodedata.name(char, "UNKNOWN")
    for script in (
        "LATIN",
        "GREEK",
        "CYRILLIC",
        "ARABIC",
        "HEBREW",
        "THAI",
        "HANGUL",
        "HIRAGANA",
        "KATAKANA",
        "DEVANAGARI",
        "BENGALI",
        "TIBETAN",
        "MYANMAR",
        "GEORGIAN",
        "ARMENIAN",
        "ETHIOPIC",
        "KHMER",
        "LAO",
        "SINHALA",
    ):
        if script in name:
            return script
    return name.split(" ", 1)[0]
