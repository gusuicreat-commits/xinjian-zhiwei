from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from app.models import Document


class Parser(ABC):
    @abstractmethod
    def parse(self, path: Path) -> List[Document]:
        raise NotImplementedError

    @staticmethod
    def base_metadata(path: Path, file_type: str) -> dict:
        return {"source": path.name, "source_path": str(path.resolve()), "file_type": file_type}
