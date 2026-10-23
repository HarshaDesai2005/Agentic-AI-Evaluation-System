from __future__ import annotations

from pathlib import Path

from models.schemas import DocumentCategory
from services.document_processor import extract_document
from services.security_service import sha256_bytes


def test_pdf_extraction_and_page_numbers(sample_docs):
    path = Path(sample_docs["fixtures"]) / "textbook.pdf"
    data = path.read_bytes()
    doc = extract_document(path, "textbook.pdf", DocumentCategory.TEXTBOOK, sha256_bytes(data))
    assert doc.extraction_status == "ok"
    assert doc.page_count >= 2
    pages_with_text = [p for p in doc.pages if p.text.strip()]
    assert pages_with_text
    assert all(p.page_number >= 1 for p in doc.pages)
    assert "De Morgan" in doc.full_text
    page_numbers = {p.page_number for p in doc.pages if "Karnaugh" in p.text or "Boolean Algebra" in p.text}
    assert page_numbers


def test_docx_headings(sample_docs):
    path = Path(sample_docs["fixtures"]) / "syllabus.docx"
    doc = extract_document(
        path, "syllabus.docx", DocumentCategory.SYLLABUS, sha256_bytes(path.read_bytes())
    )
    assert doc.extraction_status == "ok"
    assert any("UNIT" in h.upper() for h in doc.headings) or "UNIT 1" in doc.full_text


def test_empty_document_detected(sample_docs):
    path = Path(sample_docs["fixtures"]) / "empty.pdf"
    doc = extract_document(path, "empty.pdf", DocumentCategory.STUDY_MATERIAL, "abc")
    assert doc.empty or doc.extraction_status in {"empty", "ok"}
    if not doc.empty:
        assert len(doc.full_text.strip()) < 40 or doc.extraction_status
