"""Standalone parser child. No application configuration, database or credentials."""

import csv
import io
import json
import resource
import signal
import sys
import zipfile
import zlib
from xml.etree import ElementTree


class KnowledgeServiceError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code = status, code


def extract(raw, suffix, max_bytes, max_chars, max_pages):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        if suffix in {".txt", ".md"}:
            return raw.decode("utf-8"), f"{suffix[1:]}-utf8"
        if suffix == ".csv":
            rows = csv.reader(io.StringIO(raw.decode("utf-8-sig")))
            return "\n".join(" | ".join(cell.strip() for cell in row) for row in rows), "csv-v1"
        if suffix == ".docx":
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > max_bytes:
                    raise KnowledgeServiceError(
                        413,
                        "KNOWLEDGE_FILE_TOO_LARGE",
                        "Expanded DOCX XML exceeds byte limit",
                    )
                with archive.open(info) as document:
                    document_xml = document.read(max_bytes + 1)
                if len(document_xml) > max_bytes:
                    raise KnowledgeServiceError(
                        413,
                        "KNOWLEDGE_FILE_TOO_LARGE",
                        "Expanded DOCX XML exceeds byte limit",
                    )
            root = ElementTree.fromstring(document_xml)
            namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            paragraphs = []
            for paragraph in root.iter(f"{namespace}p"):
                text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t"))
                if text.strip():
                    paragraphs.append(text)
            return "\n".join(paragraphs), "docx-xml-v1"
        reader = PdfReader(io.BytesIO(raw))
        if len(reader.pages) > max_pages:
            raise KnowledgeServiceError(413, "KNOWLEDGE_PARSE_LIMIT", "Page budget exceeded")
        pages = []
        count = 0
        for page in reader.pages:
            value = (page.extract_text() or "").strip()
            count += len(value) + 2
            if count > max_chars:
                raise KnowledgeServiceError(413, "KNOWLEDGE_PARSE_LIMIT", "Text budget exceeded")
            if value:
                pages.append(value)
        text = "\n\n".join(pages)
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
        NotImplementedError,
        RuntimeError,
        zlib.error,
        ElementTree.ParseError,
        PdfReadError,
    ) as error:
        raise KnowledgeServiceError(
            422,
            "KNOWLEDGE_FILE_PARSE_FAILED",
            "Knowledge file could not be parsed safely",
        ) from error


def main():
    input_path, output_path, suffix, config_json = sys.argv[1:]
    config = json.loads(config_json)
    if sys.platform != "linux":
        raise SystemExit(78)
    signal.alarm(config["wall"])
    try:
        for kind, value in (
            (resource.RLIMIT_AS, config["memory"]),
            (resource.RLIMIT_CPU, config["cpu"]),
            (resource.RLIMIT_FSIZE, config["output_bytes"]),
            (resource.RLIMIT_CORE, 0),
        ):
            resource.setrlimit(kind, (value, value))
        with open(input_path, "rb") as handle:
            raw = handle.read(config["max_bytes"] + 1)
        if len(raw) > config["max_bytes"]:
            raise KnowledgeServiceError(413, "KNOWLEDGE_FILE_TOO_LARGE", "")
        text, parser = extract(
            raw, suffix, config["max_bytes"], config["max_chars"], config["max_pages"]
        )
        if len(text) > config["max_chars"]:
            raise KnowledgeServiceError(413, "KNOWLEDGE_PARSE_LIMIT", "")
        result = {"text": text, "parser": parser}
    except KnowledgeServiceError as error:
        result = {"status": error.status, "code": error.code}
    except MemoryError:
        result = {"status": 413, "code": "KNOWLEDGE_PARSE_LIMIT"}
    except (ValueError, OSError):
        result = {"status": 503, "code": "KNOWLEDGE_PARSER_UNAVAILABLE"}
    except Exception:
        result = {"status": 422, "code": "KNOWLEDGE_FILE_PARSE_FAILED"}
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=True)


if __name__ == "__main__":
    main()
