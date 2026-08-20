from __future__ import annotations

import hashlib
import json
import re
from typing import Iterable, List

from app.cleaning import clean_text
from app.models import Chunk, Document


class StructureChunker:
    """Split within parser-provided structural units, preferring paragraph/sentence boundaries."""

    def __init__(self, chunk_size: int = 1000, overlap: int = 120) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap must satisfy 0 <= overlap < chunk_size")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, documents: Iterable[Document], document_id: str) -> List[Chunk]:
        chunks: List[Chunk] = []
        for unit_index, document in enumerate(documents):
            content = clean_text(document.content)
            if not content:
                continue
            pieces = self._split(content)
            for piece_index, piece in enumerate(pieces):
                metadata = {
                    **document.metadata,
                    "unit_index": unit_index,
                    "chunk_index": piece_index,
                }
                content_hash = hashlib.sha256(piece.encode("utf-8")).hexdigest()
                identity = json.dumps(metadata, sort_keys=True, ensure_ascii=False, default=str)
                chunk_id = hashlib.sha256(
                    f"{document_id}\0{identity}\0{content_hash}".encode("utf-8")
                ).hexdigest()
                chunks.append(
                    Chunk(
                        id=chunk_id,
                        document_id=document_id,
                        content=piece,
                        content_hash=content_hash,
                        source=str(document.metadata.get("source", "")),
                        metadata=metadata,
                    )
                )
        return chunks

    def _split(self, text: str) -> List[str]:
        if len(text) <= self.chunk_size:
            return [text]
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        atoms: List[str] = []
        for paragraph in paragraphs:
            if len(paragraph) <= self.chunk_size:
                atoms.append(paragraph)
            else:
                atoms.extend(self._sentences(paragraph))

        result: List[str] = []
        current = ""
        for atom in atoms:
            separator = "\n\n" if current else ""
            if len(current) + len(separator) + len(atom) <= self.chunk_size:
                current += separator + atom
                continue
            if current:
                result.append(current)
                prefix = current[-self.overlap :] if self.overlap else ""
                current = prefix + ("\n" if prefix else "")
            while len(current) + len(atom) > self.chunk_size:
                room = self.chunk_size - len(current)
                current += atom[:room]
                result.append(current)
                prefix = current[-self.overlap :] if self.overlap else ""
                atom = atom[room:]
                current = prefix
            current += atom
        if current:
            result.append(current)
        return result

    def _sentences(self, paragraph: str) -> List[str]:
        sentences = [
            value.strip()
            for value in re.split(r"(?<=[。！？!?；;\.])\s*", paragraph)
            if value.strip()
        ]
        return sentences or [paragraph]
