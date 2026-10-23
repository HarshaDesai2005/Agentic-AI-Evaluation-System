from __future__ import annotations

from pathlib import Path

from models.schemas import DocumentCategory, ExtractedDocument, ExtractedPage
from services.document_processor import extract_document
from services.question_parser import apply_confirmed_marks, parse_question_paper
from services.security_service import sha256_bytes


def _paper(text: str) -> ExtractedDocument:
    return ExtractedDocument(
        original_filename="paper.pdf",
        stored_filename="paper.pdf",
        file_type=".pdf",
        category=DocumentCategory.QUESTION_PAPER,
        page_count=1,
        pages=[ExtractedPage(page_number=1, text=text)],
        full_text=text,
        sha256="x",
    )


def test_parse_common_engineering_format(sample_docs):
    path = Path(sample_docs["fixtures"]) / "question_paper.pdf"
    doc = extract_document(
        path, "question_paper.pdf", DocumentCategory.QUESTION_PAPER, sha256_bytes(path.read_bytes())
    )
    paper = parse_question_paper(doc, "Digital Logic Design", "CS301")
    numbers = {q.display_number for q in paper.questions}
    assert "1(a)" in numbers or "1" in {q.question_number for q in paper.questions}
    assert paper.printed_total_marks == 48
    subs = [q for q in paper.questions if q.subquestion_number]
    assert subs
    choice = [q for q in paper.questions if q.is_internal_choice or q.choice_group]
    assert choice, "Internal choice in Q5 should be detected"
    marks = {q.display_number: q.marks for q in paper.questions}
    assert 5.0 in marks.values()
    assert 10.0 in marks.values()


def test_missing_marks_are_not_invented():
    text = """
    Maximum Marks: 20
    Q1 Explain Boolean algebra.
    Q2 (a) Convert 101 to decimal.
    """
    paper = parse_question_paper(_paper(text), "DLD", "CS301")
    assert any(q.marks is None for q in paper.questions)
    assert any("never invented" in w.lower() or "missing" in w.lower() for w in paper.parse_warnings)
    updated = apply_confirmed_marks(paper, {paper.questions[0].id: 7})
    assert updated.questions[0].marks == 7
    assert updated.questions[0].marks_confirmed


def test_internal_choice_or_block():
    text = """
    Q5 Answer any one of the following.
    (a) Minimise using K-map. (10 marks)
    OR
    (b) Explain FPGA architecture. (10 marks)
    """
    paper = parse_question_paper(_paper(text), "DLD", "CS301")
    assert len(paper.questions) >= 2
    assert any(q.is_internal_choice or q.choice_group for q in paper.questions)
