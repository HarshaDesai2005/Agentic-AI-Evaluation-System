from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from database import db  # noqa: E402
from scripts.create_sample_docs import write_all  # noqa: E402


class LexicalEmbedder:
    dim = 64
    backend = "lexical"
    model_name = "lexical-test"

    def load(self) -> None:
        return None

    def embed(self, texts):
        rows = [self._vec(t) for t in texts]
        return np.vstack(rows)

    def embed_one(self, text: str):
        return self._vec(text)

    def _vec(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype="float32")
        for word in (text or "").lower().split():
            token = "".join(ch for ch in word if ch.isalnum())
            if not token:
                continue
            vec[hash(token) % self.dim] += 1.0
        norm = np.linalg.norm(vec) + 1e-9
        return vec / norm


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "INDEX_DIR", tmp_path / "indexes")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "outputs")
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    db.init_db()
    yield


@pytest.fixture(scope="session")
def sample_docs():
    return write_all()


@pytest.fixture
def lexical_embedder():
    return LexicalEmbedder()
