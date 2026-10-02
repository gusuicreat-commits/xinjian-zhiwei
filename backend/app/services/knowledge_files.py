import base64
import binascii
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from app.core.config import Settings
from app.services.knowledge import KnowledgeServiceError

SUPPORTED_SUFFIXES = {".txt", ".md", ".csv", ".docx", ".pdf"}


def decode_and_extract(
    filename: str,
    content_base64: str,
    max_bytes: int,
    *,
    settings: Settings | None = None,
) -> tuple[str, str]:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise KnowledgeServiceError(
            422,
            "UNSUPPORTED_KNOWLEDGE_FILE",
            "Supported file types are TXT, Markdown, CSV, DOCX and extractable PDF",
        )
    if len(content_base64) > 4 * ((max_bytes + 2) // 3):
        raise KnowledgeServiceError(
            413, "KNOWLEDGE_FILE_TOO_LARGE", "Encoded file exceeds byte limit"
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
    settings = settings or Settings(_env_file=None)
    if sys.platform != "linux":
        raise KnowledgeServiceError(
            503, "KNOWLEDGE_PARSER_UNAVAILABLE", "Bounded file parsing requires the Linux service"
        )
    config = {
        "max_bytes": max_bytes,
        "max_chars": settings.knowledge_max_document_chars,
        "max_pages": settings.knowledge_parser_max_pages,
        "memory": settings.knowledge_parser_memory_bytes,
        "cpu": settings.knowledge_parser_cpu_seconds,
        "wall": settings.knowledge_parser_wall_seconds,
        "output_bytes": settings.knowledge_max_document_chars * 12 + 4096,
    }
    with (
        _parser_slot(settings.knowledge_parser_concurrency),
        tempfile.TemporaryDirectory(prefix="xinjian-parser-") as directory,
    ):
        source = Path(directory) / "input"
        target = Path(directory) / "output"
        source.write_bytes(raw)
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                str(Path(__file__).with_name("knowledge_parser_worker.py")),
                str(source),
                str(target),
                suffix,
                json.dumps(config),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={"PATH": os.defpath, "LANG": "C.UTF-8"},
            close_fds=True,
        )
        try:
            process.wait(timeout=settings.knowledge_parser_wall_seconds)
        except subprocess.TimeoutExpired as error:
            process.kill()
            process.wait()
            raise KnowledgeServiceError(
                413, "KNOWLEDGE_PARSE_LIMIT", "Parsing budget exceeded"
            ) from error
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        if process.returncode != 0 or not target.exists():
            raise KnowledgeServiceError(413, "KNOWLEDGE_PARSE_LIMIT", "Parsing budget exceeded")
        with target.open("rb") as handle:
            encoded = handle.read(config["output_bytes"] + 1)
        if len(encoded) > config["output_bytes"]:
            raise KnowledgeServiceError(413, "KNOWLEDGE_PARSE_LIMIT", "Parsing budget exceeded")
        result = json.loads(encoded)
        if "status" in result:
            raise KnowledgeServiceError(result["status"], result["code"], "File parsing rejected")
        return result["text"], result["parser"]


@contextmanager
def _parser_slot(limit):
    """Nonblocking, cross-worker admission on this service host."""
    import fcntl

    directory = Path(tempfile.gettempdir()) / f"xinjian-parser-slots-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    descriptor = None
    for index in range(limit):
        candidate = os.open(directory / str(index), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
            descriptor = candidate
            break
        except BlockingIOError:
            os.close(candidate)
    if descriptor is None:
        raise KnowledgeServiceError(503, "KNOWLEDGE_PARSER_BUSY", "Parser capacity is occupied")
    try:
        yield
    finally:
        os.close(descriptor)
