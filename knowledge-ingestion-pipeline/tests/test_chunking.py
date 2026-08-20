from app.chunking import StructureChunker
from app.models import Document


def test_chunk_preserves_metadata_and_ids_are_stable() -> None:
    document = Document(
        content="First diagnostic paragraph.\n\nSecond diagnostic paragraph with details.",
        metadata={"source": "manual.md", "file_type": "md", "section": "I2C"},
    )
    chunker = StructureChunker(chunk_size=45, overlap=8)
    first = chunker.chunk([document], "document-hash")
    second = chunker.chunk([document], "document-hash")

    assert len(first) >= 2
    assert [chunk.id for chunk in first] == [chunk.id for chunk in second]
    assert all(chunk.metadata["section"] == "I2C" for chunk in first)
    assert all(chunk.source == "manual.md" for chunk in first)
    assert all(len(chunk.content) <= 45 for chunk in first)
