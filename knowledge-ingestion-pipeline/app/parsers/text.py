from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from app.models import Document
from app.parsers.base import Parser


class TextParser(Parser):
    def __init__(self, markdown: bool = False) -> None:
        self.markdown = markdown

    def parse(self, path: Path) -> List[Document]:
        text = path.read_text(encoding="utf-8-sig")
        base = self.base_metadata(path, "md" if self.markdown else "txt")
        if not self.markdown:
            return [Document(content=text, metadata=base)]

        documents: List[Document] = []
        section: Optional[str] = None
        buffer: List[str] = []
        for line in text.splitlines():
            heading = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", line)
            if heading:
                self._flush(documents, buffer, base, section)
                buffer = []
                section = heading.group(2).strip()
            else:
                buffer.append(line)
        self._flush(documents, buffer, base, section)
        return documents or [Document(content="", metadata=base)]

    @staticmethod
    def _flush(
        documents: List[Document], buffer: List[str], base: dict, section: Optional[str]
    ) -> None:
        content = "\n".join(buffer).strip()
        if content:
            metadata = {**base, "section": section} if section else dict(base)
            documents.append(Document(content=content, metadata=metadata))
