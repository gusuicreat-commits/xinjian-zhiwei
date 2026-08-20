from __future__ import annotations

from typing import List, Sequence

from app.embeddings.base import EmbeddingProvider


class QwenEmbeddingProvider(EmbeddingProvider):
    """Lazy-loaded local Qwen3 embedding model with MPS/CPU device selection."""

    def __init__(self, model_source: str, device: str = "auto", batch_size: int = 16) -> None:
        self.model_source = model_source
        self.device = self._resolve_device(device)
        self.batch_size = batch_size
        self._model = None

    @property
    def model_name(self) -> str:
        return self.model_source

    @staticmethod
    def _resolve_device(requested: str) -> str:
        if requested != "auto":
            return requested
        try:
            import torch

            if torch.backends.mps.is_available():
                return "mps"
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                self.model_source,
                device=self.device,
                trust_remote_code=True,
            )
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        vectors = self._load().encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=len(texts) > self.batch_size,
        )
        return vectors.tolist()
