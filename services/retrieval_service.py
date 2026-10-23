"""Chunking, local vector index (FAISS or NumPy), and retrieval."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

import config
from database import db
from models.schemas import DocumentCategory, ExtractedDocument, SourceEvidence, TextChunk
from services.embedding_service import EmbeddingService, get_embedding_service
from services.logging_config import logger

INDEX_META = "metadata.json"
INDEX_VEC = "vectors.npy"
INDEX_FAISS = "index.faiss"


def clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_document(
    document: ExtractedDocument, subject: Optional[str] = None
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    for page in document.pages:
        raw = clean_text(page.text)
        if not raw:
            continue
        pieces = _split_units(raw, page.heading)
        for piece, section in pieces:
            for window in _windows(piece):
                chunks.append(
                    TextChunk(
                        chunk_id=str(uuid.uuid4()),
                        text=window,
                        filename=document.original_filename,
                        document_type=document.category.value,
                        page_number=page.page_number,
                        section=section or page.heading,
                        subject=subject,
                        syllabus_unit=_guess_unit(section or page.heading or window),
                        sha256=document.sha256,
                    )
                )
    return chunks


def _guess_unit(text: str) -> Optional[str]:
    match = re.search(r"(unit\s*[-:]?\s*\d+|module\s*[-:]?\s*\d+)", text or "", re.I)
    return match.group(1) if match else None


def _split_units(text: str, fallback_heading: Optional[str]) -> list[tuple[str, Optional[str]]]:
    parts = re.split(r"(?m)^(#{1,3}\s+.+)$", text)
    if len(parts) == 1:
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        return [(p, fallback_heading) for p in paras] or [(text, fallback_heading)]
    out: list[tuple[str, Optional[str]]] = []
    heading = fallback_heading
    for part in parts:
        if re.match(r"^#{1,3}\s+", part):
            heading = part.lstrip("#").strip()
            continue
        if part.strip():
            out.append((part.strip(), heading))
    return out or [(text, fallback_heading)]


def _windows(text: str) -> list[str]:
    if len(text) <= config.CHUNK_SIZE:
        return [text]
    words = text.split()
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    overlap_words = max(8, config.CHUNK_OVERLAP // 6)
    for word in words:
        buf.append(word)
        size += len(word) + 1
        if size >= config.CHUNK_SIZE:
            chunks.append(" ".join(buf))
            buf = buf[-overlap_words:]
            size = sum(len(w) + 1 for w in buf)
    if buf:
        chunk = " ".join(buf)
        if chunk and (not chunks or chunk != chunks[-1]):
            chunks.append(chunk)
    return chunks


@dataclass
class SearchHit:
    chunk: TextChunk
    score: float


class KnowledgeBase:
    def __init__(
        self,
        index_dir: Optional[Path] = None,
        embedder: Optional[EmbeddingService] = None,
    ) -> None:
        self.index_dir = Path(index_dir or config.INDEX_DIR)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder or get_embedding_service()
        self.chunks: list[TextChunk] = []
        self.vectors: Optional[np.ndarray] = None
        self._faiss_index = None
        self._load()

    def _meta_path(self) -> Path:
        return self.index_dir / INDEX_META

    def _vec_path(self) -> Path:
        return self.index_dir / INDEX_VEC

    def _load(self) -> None:
        meta = self._meta_path()
        vec = self._vec_path()
        if not meta.exists() or not vec.exists():
            return
        payload = json.loads(meta.read_text(encoding="utf-8"))
        self.chunks = [TextChunk.model_validate(c) for c in payload.get("chunks", [])]
        self.vectors = np.load(vec).astype("float32")
        self._maybe_faiss()

    def _maybe_faiss(self) -> None:
        if self.vectors is None or len(self.vectors) == 0:
            return
        try:
            import faiss

            index = faiss.IndexFlatIP(self.vectors.shape[1])
            index.add(self.vectors)
            self._faiss_index = index
        except Exception:
            self._faiss_index = None

    def persist(self) -> None:
        payload = {"chunks": [c.model_dump() for c in self.chunks]}
        self._meta_path().write_text(json.dumps(payload), encoding="utf-8")
        if self.vectors is not None:
            np.save(self._vec_path(), self.vectors)
        self._maybe_faiss()

    def clear(self) -> None:
        self.chunks = []
        self.vectors = None
        self._faiss_index = None
        if self.index_dir.exists():
            shutil.rmtree(self.index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        db.clear_kb_documents()

    def remove_by_hash(self, sha256: str) -> None:
        keep = [c for c in self.chunks if c.sha256 != sha256]
        if len(keep) == len(self.chunks):
            return
        indices = [i for i, c in enumerate(self.chunks) if c.sha256 != sha256]
        self.chunks = keep
        if self.vectors is not None and indices:
            self.vectors = self.vectors[indices]
        else:
            self.vectors = None
        self.persist()
        row = db.get_kb_by_hash(sha256)
        if row:
            db.delete_kb_document(row["id"])

    def add_document(
        self,
        document: ExtractedDocument,
        subject: Optional[str] = None,
        skip_if_unchanged: bool = True,
        register_in_db: bool = True,
    ) -> dict[str, Any]:
        if skip_if_unchanged and register_in_db and db.get_kb_by_hash(document.sha256):
            return {"status": "skipped_duplicate", "chunks": 0, "filename": document.original_filename}
        if document.empty or not document.full_text.strip():
            return {"status": "empty", "chunks": 0, "filename": document.original_filename}
        new_chunks = chunk_document(document, subject=subject)
        if not new_chunks:
            return {"status": "empty", "chunks": 0, "filename": document.original_filename}
        vectors = self.embedder.embed([c.text for c in new_chunks])
        if self.vectors is None or len(self.chunks) == 0:
            self.chunks = new_chunks
            self.vectors = vectors
        else:
            self.chunks.extend(new_chunks)
            self.vectors = np.vstack([self.vectors, vectors])
        self.persist()
        if register_in_db:
            db.upsert_kb_document(
                {
                    "id": str(uuid.uuid4()),
                    "filename": document.original_filename,
                    "category": document.category.value,
                    "sha256": document.sha256,
                    "chunk_count": len(new_chunks),
                    "subject": subject,
                    "stored_path": document.stored_filename,
                }
            )
        logger.info("Indexed %s chunks from %s", len(new_chunks), document.stored_filename)
        return {
            "status": "indexed",
            "chunks": len(new_chunks),
            "filename": document.original_filename,
        }

    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        document_types: Optional[list[str]] = None,
        min_score: Optional[float] = None,
    ) -> list[SearchHit]:
        if not self.chunks or self.vectors is None or not query.strip():
            return []
        top_k = top_k or config.TOP_K
        min_score = config.RETRIEVAL_MIN_SCORE if min_score is None else min_score
        q = self.embedder.embed_one(query).astype("float32")
        if self._faiss_index is not None:
            scores, idxs = self._faiss_index.search(q.reshape(1, -1), min(top_k * 4, len(self.chunks)))
            ranked = [(float(scores[0][i]), int(idxs[0][i])) for i in range(len(idxs[0])) if idxs[0][i] >= 0]
        else:
            sims = self.vectors @ q
            order = np.argsort(-sims)
            ranked = [(float(sims[i]), int(i)) for i in order[: top_k * 4]]
        hits: list[SearchHit] = []
        for score, idx in ranked:
            chunk = self.chunks[idx]
            if document_types and chunk.document_type not in document_types:
                continue
            if score < min_score:
                continue
            hits.append(SearchHit(chunk=chunk, score=score))
            if len(hits) >= top_k:
                break
        return hits

    def as_evidence(self, hits: list[SearchHit]) -> list[SourceEvidence]:
        evidence = []
        for hit in hits:
            evidence.append(
                SourceEvidence(
                    filename=hit.chunk.filename,
                    document_type=hit.chunk.document_type,
                    page_number=hit.chunk.page_number,
                    section=hit.chunk.section,
                    quote=hit.chunk.text[:500],
                    score=round(hit.score, 4),
                    verified=True,
                    kind="document",
                )
            )
        return evidence

    def stats(self) -> dict[str, Any]:
        types: dict[str, int] = {}
        for c in self.chunks:
            types[c.document_type] = types.get(c.document_type, 0) + 1
        backend = "faiss" if self._faiss_index is not None else "numpy"
        unique_docs = {c.sha256 for c in self.chunks}
        return {
            "chunk_count": len(self.chunks),
            "documents": len(unique_docs),
            "backend": backend,
            "types": types,
        }


_kb: Optional[KnowledgeBase] = None


def get_knowledge_base() -> KnowledgeBase:
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb


def supporting_types() -> list[str]:
    return [
        DocumentCategory.TEXTBOOK.value,
        DocumentCategory.STUDY_MATERIAL.value,
        DocumentCategory.PREVIOUS_SCHEME.value,
    ]
