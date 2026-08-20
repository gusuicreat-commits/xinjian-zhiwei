from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Sequence


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def model_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]
