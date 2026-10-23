from __future__ import annotations

from pathlib import Path

import numpy as np

from models.schemas import DocumentCategory
from services.document_processor import extract_document
from services.retrieval_service import KnowledgeBase, chunk_document
from services.security_service import sha256_bytes


def test_chunk_metadata_preserved(sample_docs, tmp_path, lexical_embedder):
    path = Path(sample_docs["fixtures"]) / "textbook.pdf"
    doc = extract_document(path, "textbook.pdf", DocumentCategory.TEXTBOOK, sha256_bytes(path.read_bytes()))
    chunks = chunk_document(doc, subject="DLD")
    assert chunks
    assert all(c.filename == "textbook.pdf" for c in chunks)
    assert all(c.document_type == "textbook" for c in chunks)
    assert any(c.page_number and c.page_number >= 1 for c in chunks)
    assert any("De Morgan" in c.text for c in chunks)


def test_retrieval_ranks_relevant_chunk(tmp_path, lexical_embedder, sample_docs):
    kb = KnowledgeBase(index_dir=tmp_path / "idx", embedder=lexical_embedder)
    path = Path(sample_docs["fixtures"]) / "syllabus.docx"
    doc = extract_document(path, "syllabus.docx", DocumentCategory.SYLLABUS, sha256_bytes(path.read_bytes()))
    kb.add_document(doc, subject="DLD", skip_if_unchanged=False)
    hits = kb.search("De Morgan theorems Boolean algebra", document_types=["syllabus"], min_score=0.01)
    assert hits
    assert any("Boolean" in h.chunk.text or "De Morgan" in h.chunk.text for h in hits)
    assert hits[0].score >= hits[-1].score


def test_duplicate_indexing_skipped(tmp_path, lexical_embedder, sample_docs, monkeypatch):
    kb = KnowledgeBase(index_dir=tmp_path / "idx2", embedder=lexical_embedder)
    path = Path(sample_docs["fixtures"]) / "notes.docx"
    doc = extract_document(path, "notes.docx", DocumentCategory.STUDY_MATERIAL, sha256_bytes(path.read_bytes()))
    first = kb.add_document(doc, skip_if_unchanged=False)
    second = kb.add_document(doc, skip_if_unchanged=True)
    assert first["status"] == "indexed"
    assert second["status"] == "skipped_duplicate"
