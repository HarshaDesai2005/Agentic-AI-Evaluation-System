"""Local Sentence Transformers embeddings with a hash fallback for tests."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from typing import Iterable, Optional

import numpy as np

import config
from services.logging_config import logger

_model = None
_use_hash_fallback = False


def _hash_vector(text: str, dim: int = 384) -> np.ndarray:
    digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
    vec = rng.standard_normal(dim).astype("float32")
    norm = np.linalg.norm(vec) + 1e-9
    return vec / norm


class EmbeddingService:
    def __init__(self, allow_hash_fallback: bool = False) -> None:
        self.allow_hash_fallback = allow_hash_fallback
        self.model_name = config.EMBEDDING_MODEL
        self._model = None
        self.backend = "unloaded"

    def load(self) -> None:
        if self._model is not None or self.backend == "hash":
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                self.model_name, cache_folder=str(config.MODEL_CACHE_DIR)
            )
            self.backend = "sentence-transformers"
            logger.info("Loaded embedding model %s", self.model_name)
        except Exception as exc:  # noqa: BLE001
            if self.allow_hash_fallback:
                self.backend = "hash"
                logger.info("Using hash embeddings for tests: %s", type(exc).__name__)
                return
            raise RuntimeError(
                "Could not load the local embedding model "
                f"'{self.model_name}'. Check internet access on first download "
                "or place the model in data/model_cache. "
                f"Details: {type(exc).__name__}"
            ) from exc

    @property
    def dim(self) -> int:
        self.load()
        if self.backend == "hash":
            return 384
        return int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: Iterable[str]) -> np.ndarray:
        items = [t if t.strip() else " " for t in texts]
        self.load()
        if self.backend == "hash":
            return np.vstack([_hash_vector(t) for t in items])
        vectors = self._model.encode(
            items,
            convert_to_numpy=True,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return np.asarray(vectors, dtype="float32")

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


@lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService(allow_hash_fallback=False)


def status_message(service: Optional[EmbeddingService] = None) -> str:
    service = service or get_embedding_service()
    try:
        service.load()
        return f"Ready ({service.backend}: {service.model_name})"
    except Exception as exc:  # noqa: BLE001
        return f"Unavailable ({type(exc).__name__})"
