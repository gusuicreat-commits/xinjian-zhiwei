import asyncio
import base64
import io
import sys

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.api.knowledge_body_limit import KnowledgeBodyLimit
from app.core.config import Settings
from app.services.knowledge import KnowledgeServiceError
from app.services.knowledge_files import _parser_slot, decode_and_extract


def settings(**kw):
    return Settings(_env_file=None, **kw)


@pytest.mark.parametrize("headers", [[], [(b"content-length", b"1")]])
def test_upload_actual_count_stops_before_application(headers):
    called = []
    sent = []

    async def application(*args):
        called.append(True)

    middleware = KnowledgeBodyLimit(
        application, settings(knowledge_max_file_bytes=3, knowledge_request_metadata_bytes=1024)
    )
    messages = iter(
        [
            {"type": "http.request", "body": b"x" * 1000, "more_body": True},
            {"type": "http.request", "body": b"x" * 29, "more_body": False},
        ]
    )

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    asyncio.run(
        middleware(
            {
                "type": "http",
                "method": "POST",
                "headers": headers,
                "path": "/api/v1/knowledge/sources/a/documents/file",
            },
            receive,
            send,
        )
    )
    assert not called
    assert sent[0]["status"] == 413


def test_legal_body_is_replayed_exactly():
    received = []
    body = b"{}"

    async def application(scope, receive, send):
        received.append((await receive())["body"])

    async def receive():
        return {"type": "http.request", "body": body}

    asyncio.run(
        KnowledgeBodyLimit(application, settings())(
            {
                "type": "http",
                "method": "POST",
                "headers": [],
                "path": "/api/v1/knowledge/sources/a/documents/file",
            },
            receive,
            None,
        )
    )
    assert received == [body]


def test_unsupported_platform_is_explicitly_unavailable(monkeypatch):
    monkeypatch.setattr("app.services.knowledge_files.sys.platform", "darwin")
    with pytest.raises(KnowledgeServiceError) as error:
        decode_and_extract("a.txt", base64.b64encode(b"hello").decode(), 100)
    assert error.value.status_code == 503
    assert error.value.code == "KNOWLEDGE_PARSER_UNAVAILABLE"


@pytest.mark.skipif(sys.platform != "linux", reason="Real resource limits require Linux")
def test_linux_normal_near_text_limit_and_overflow():
    config = settings(knowledge_max_document_chars=500_000)
    assert (
        len(
            decode_and_extract(
                "a.txt", base64.b64encode(b"a" * 500_000).decode(), 1_000_000, settings=config
            )[0]
        )
        == 500_000
    )
    with pytest.raises(KnowledgeServiceError) as error:
        decode_and_extract(
            "a.txt", base64.b64encode(b"a" * 500_001).decode(), 1_000_000, settings=config
        )
    assert error.value.status_code == 413
    assert decode_and_extract("a.txt", base64.b64encode(b"hello").decode(), 100)[0] == "hello"


@pytest.mark.skipif(sys.platform != "linux", reason="Real resource limits require Linux")
def test_linux_pdf_page_and_expansion_limits():
    writer = PdfWriter()
    for _ in range(3):
        page = writer.add_blank_page(width=612, height=792)
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 10 700 Td (" + b"x" * 10_000 + b") Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream.flate_encode())
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
    buffer = io.BytesIO()
    writer.write(buffer)
    encoded = base64.b64encode(buffer.getvalue()).decode()
    for config in (
        settings(knowledge_parser_max_pages=2),
        settings(knowledge_max_document_chars=20_000),
    ):
        with pytest.raises(KnowledgeServiceError) as error:
            decode_and_extract("a.pdf", encoded, 100_000, settings=config)
        assert error.value.status_code == 413


def test_concurrent_parser_capacity_is_explicit():
    with _parser_slot(1), pytest.raises(KnowledgeServiceError) as error:
        with _parser_slot(1):
            pass
    assert error.value.code == "KNOWLEDGE_PARSER_BUSY"
    with _parser_slot(1):
        pass


@pytest.mark.skipif(sys.platform != "linux", reason="Real resource limits require Linux")
@pytest.mark.parametrize("operation", ["memory", "cpu", "wall"])
def test_linux_resource_termination_reaps_child(tmp_path, monkeypatch, operation):
    import subprocess
    from pathlib import Path

    from app.services import knowledge_files

    worker = Path(knowledge_files.__file__).with_name("knowledge_parser_worker.py")
    attack = tmp_path / "attack.py"
    expression = {
        "memory": "return 'x' * (512 * 1024 * 1024), 'synthetic'",
        "cpu": "while True: pass",
        "wall": "time.sleep(20)",
    }[operation]
    attack.write_text(
        "import importlib.util,time\n"
        f'spec=importlib.util.spec_from_file_location("worker", {str(worker)!r})\n'
        "worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)\n"
        "def adversarial(*args):\n    " + expression + "\n"
        "worker.extract=adversarial\nworker.main()\n"
    )
    real_popen = subprocess.Popen
    children = []

    def launch(arguments, **kwargs):
        arguments[2] = str(attack)
        child = real_popen(arguments, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(knowledge_files.subprocess, "Popen", launch)
    with pytest.raises(KnowledgeServiceError) as error:
        decode_and_extract(
            "a.txt",
            base64.b64encode(b"hello").decode(),
            100,
            settings=settings(knowledge_parser_cpu_seconds=1, knowledge_parser_wall_seconds=2),
        )
    assert error.value.status_code == 413
    assert all(child.poll() is not None for child in children)
    monkeypatch.setattr(knowledge_files.subprocess, "Popen", real_popen)
    assert decode_and_extract("a.txt", base64.b64encode(b"hello").decode(), 100)[0] == "hello"


def test_disconnected_upload_does_not_enter_application():
    called = []

    async def application(*args):
        called.append(True)

    async def receive():
        return {"type": "http.disconnect"}

    asyncio.run(
        KnowledgeBodyLimit(application, settings())(
            {
                "type": "http",
                "method": "POST",
                "headers": [],
                "path": "/api/v1/knowledge/sources/a/documents/file",
            },
            receive,
            None,
        )
    )
    assert not called


@pytest.mark.skipif(sys.platform != "linux", reason="Real resource limits require Linux")
def test_linux_unavailable_resource_limit_fails_closed(tmp_path, monkeypatch):
    import subprocess
    from pathlib import Path

    from app.services import knowledge_files

    worker = Path(knowledge_files.__file__).with_name("knowledge_parser_worker.py")
    unavailable = tmp_path / "unavailable.py"
    unavailable.write_text(
        "import importlib.util\n"
        f'spec=importlib.util.spec_from_file_location("worker", {str(worker)!r})\n'
        "worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)\n"
        'def deny(*args): raise ValueError("synthetic resource limit unavailable")\n'
        "worker.resource.setrlimit=deny\nworker.main()\n"
    )
    real_popen = subprocess.Popen

    def launch(arguments, **kwargs):
        arguments[2] = str(unavailable)
        return real_popen(arguments, **kwargs)

    monkeypatch.setattr(knowledge_files.subprocess, "Popen", launch)
    with pytest.raises(KnowledgeServiceError) as error:
        decode_and_extract("a.txt", base64.b64encode(b"hello").decode(), 100)
    assert error.value.status_code == 503
    assert error.value.code == "KNOWLEDGE_PARSER_UNAVAILABLE"


@pytest.mark.parametrize("headers", [[], [(b"content-length", b"1")]])
def test_edit_actual_bytes_are_bounded_before_json(headers):
    called = []
    sent = []

    async def application(*args):
        called.append(True)

    messages = iter(
        [
            {"type": "http.request", "body": b"x" * 1024, "more_body": True},
            {"type": "http.request", "body": b"x" * 13, "more_body": False},
        ]
    )

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    asyncio.run(
        KnowledgeBodyLimit(
            application,
            settings(knowledge_max_document_chars=1, knowledge_request_metadata_bytes=1024),
        )(
            {
                "type": "http",
                "method": "PATCH",
                "headers": headers,
                "path": "/api/v1/knowledge/chunks/a",
            },
            receive,
            send,
        )
    )
    assert not called
    assert sent[0]["status"] == 413
