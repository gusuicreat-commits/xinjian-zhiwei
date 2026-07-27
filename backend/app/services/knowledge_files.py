import base64
import binascii
import csv
import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.services.knowledge import KnowledgeServiceError

SUPPORTED_SUFFIXES = {".txt", ".md", ".csv", ".docx", ".pdf"}


def decode_and_extract(
    filename: str,
    content_base64: str,
    max_bytes: int,
) -> tuple[str, str]:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise KnowledgeServiceError(
            422,
            "UNSUPPORTED_KNOWLEDGE_FILE",
            "Supported file types are TXT, Markdown, CSV, DOCX and extractable PDF",
        )
    try:
        raw = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as error:
        raise KnowledgeServiceError(
            422,
            "INVALID_FILE_ENCODING",
            "content_base64 is invalid",
        ) from error
    if len(raw) > max_bytes:
        raise KnowledgeServiceError(
            413,
            "KNOWLEDGE_FILE_TOO_LARGE",
            "Knowledge file exceeds the configured byte limit",
        )
    try:
        if suffix in {".txt", ".md"}:
            return raw.decode("utf-8"), f"{suffix[1:]}-utf8"
        if suffix == ".csv":
            rows = csv.reader(io.StringIO(raw.decode("utf-8-sig")))
            return "\n".join(" | ".join(cell.strip() for cell in row) for row in rows), "csv-v1"
        if suffix == ".docx":
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                document_xml = archive.read("word/document.xml")
            root = ElementTree.fromstring(document_xml)
            namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            paragraphs = []
            for paragraph in root.iter(f"{namespace}p"):
                text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t"))
                if text.strip():
                    paragraphs.append(text)
            return "\n".join(paragraphs), "docx-xml-v1"
        reader = PdfReader(io.BytesIO(raw))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n\n".join(page.strip() for page in pages if page.strip())
        if not text:
            raise KnowledgeServiceError(
                422,
                "PDF_TEXT_NOT_EXTRACTABLE",
                "PDF has no extractable text; OCR is not enabled",
            )
        return text, "pypdf-v1"
    except KnowledgeServiceError:
        raise
    except (
        UnicodeDecodeError,
        csv.Error,
        KeyError,
        zipfile.BadZipFile,
        ElementTree.ParseError,
        PdfReadError,
    ) as error:
        raise KnowledgeServiceError(
            422,
            "KNOWLEDGE_FILE_PARSE_FAILED",
            "Knowledge file could not be parsed safely",
        ) from error
