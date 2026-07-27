import base64
import io
import zipfile

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.models import KnowledgeDocument
from app.schemas.knowledge import KnowledgeSourceCreate, KnowledgeTextImportRequest
from app.services.knowledge import (
    KnowledgeServiceError,
    create_source,
    delete_chunk,
    import_text_document,
    merge_chunks,
    split_chunk_at,
    update_chunk,
)
from app.services.knowledge_files import decode_and_extract


def _source_and_document(api_context: dict[str, object]) -> tuple[str, str]:
    with api_context["session_factory"]() as db:
        source = create_source(
            db,
            KnowledgeSourceCreate(
                source_key="synthetic.workspace",
                source_type="synthetic",
                title="合成工作区资料",
                authorization_scope="test only",
                is_test_data=True,
            ),
        )
        document = import_text_document(
            db,
            source.id,
            KnowledgeTextImportRequest(
                title="synthetic.txt",
                content="第一段合成文本。\n第二段合成文本。",
                is_test_data=True,
            ),
            Settings(
                knowledge_chunk_size_chars=100,
                knowledge_chunk_overlap_chars=0,
            ),
        )
        return source.id, document.id


def test_txt_csv_and_docx_extraction_are_deterministic() -> None:
    text, parser = decode_and_extract(
        "sample.txt",
        base64.b64encode("合成文本".encode()).decode(),
        1000,
    )
    assert (text, parser) == ("合成文本", "txt-utf8")

    csv_text, csv_parser = decode_and_extract(
        "sample.csv",
        base64.b64encode(b"a,b\n1,2").decode(),
        1000,
    )
    assert csv_text == "a | b\n1 | 2"
    assert csv_parser == "csv-v1"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
                "合成 DOCX"
                "</w:t></w:r></w:p></w:body></w:document>"
            ),
        )
    docx_text, docx_parser = decode_and_extract(
        "sample.docx",
        base64.b64encode(buffer.getvalue()).decode(),
        10000,
    )
    assert docx_text == "合成 DOCX"
    assert docx_parser == "docx-xml-v1"


def test_pdf_without_extractable_text_is_rejected_without_fake_ocr() -> None:
    with pytest.raises(KnowledgeServiceError) as error:
        decode_and_extract(
            "scan.pdf",
            base64.b64encode(b"not a pdf").decode(),
            1000,
        )
    assert error.value.code in {"PDF_TEXT_NOT_EXTRACTABLE", "KNOWLEDGE_FILE_PARSE_FAILED"}


def test_draft_workspace_supports_update_split_merge_and_guarded_delete(
    api_context: dict[str, object],
) -> None:
    _, document_id = _source_and_document(api_context)
    with api_context["session_factory"]() as db:
        document = db.get(KnowledgeDocument, document_id)
        chunk = document.chunks[0]
        workspace = update_chunk(
            db,
            chunk.id,
            content="左侧合成内容。右侧合成内容。",
            metadata={"tags": ["synthetic"], "error_codes": ["TEST_ERROR"]},
        )
        assert workspace.chunks[0].metadata["error_codes"] == ["TEST_ERROR"]
        workspace = split_chunk_at(db, workspace.chunks[0].id, 7)
        assert len(workspace.chunks) == 2
        workspace = merge_chunks(db, [item.id for item in workspace.chunks])
        assert len(workspace.chunks) == 1
        with pytest.raises(KnowledgeServiceError, match="retain at least one"):
            delete_chunk(db, workspace.chunks[0].id)
        assert db.scalar(select(func.count(KnowledgeDocument.id))) == 1
