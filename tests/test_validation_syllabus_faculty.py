from __future__ import annotations

from pathlib import Path

from agents.syllabus_compliance import classify_syllabus
from agents.validation import can_approve_scheme, criterion_sum, marks_agree, validate_question, validate_scheme
from models.schemas import (
    ApprovalStatus,
    GeneratedSolution,
    MarkingCriterion,
    QuestionPaper,
    QuestionResult,
    SourceEvidence,
    SubQuestion,
    SyllabusClassification,
    SyllabusStatus,
)
from services.export_service import export_csv, export_docx, export_pdf
from services.retrieval_service import KnowledgeBase
from services.document_processor import extract_document
from models.schemas import DocumentCategory
from services.security_service import sha256_bytes


def _q(qid="1", marks=5.0, text="Explain De Morgan theorems"):
    return SubQuestion(
        id=qid,
        question_number="1",
        display_number="1",
        text=text,
        marks=marks,
        marks_confirmed=True,
    )


def _result(marks=5.0, allocated=(2.0, 3.0), status=SyllabusStatus.IN, evidence=True):
    ev = [
        SourceEvidence(
            filename="syllabus.docx",
            page_number=1,
            quote="De Morgan's theorems",
            verified=True,
        )
    ] if evidence else []
    result = QuestionResult(
        question_id="1",
        display_number="1",
        question_text="Explain De Morgan theorems",
        marks=marks,
        solution=GeneratedSolution(solution_text="(A·B)'=A'+B'. (A+B)'=A'·B'."),
        marking_criteria=[
            MarkingCriterion(step_label="A", expected_answer="first", marks=allocated[0]),
            MarkingCriterion(step_label="B", expected_answer="second", marks=allocated[1]),
        ],
        syllabus=SyllabusClassification(status=status, reason="covered", evidence=ev, needs_faculty_review=False),
    )
    validate_question(result)
    return result


def test_marks_arithmetic():
    criteria = [
        MarkingCriterion(step_label="a", expected_answer="x", marks=2.5),
        MarkingCriterion(step_label="b", expected_answer="y", marks=2.5),
    ]
    assert criterion_sum(criteria) == 5.0
    assert marks_agree(5.0, 5.0)
    assert not marks_agree(4.0, 5.0)


def test_marks_mismatch_blocks_auto_approval():
    result = _result(allocated=(1.0, 1.0))
    assert result.marks_match is False
    paper = QuestionPaper(subject_name="DLD", subject_code="CS301", questions=[_q()], printed_total_marks=5)
    scheme = validate_scheme(paper, [result])
    ok, _ = can_approve_scheme(scheme)
    assert ok is False


def test_missing_evidence_downgrades_out():
    result = _result(status=SyllabusStatus.OUT, evidence=False)
    assert result.syllabus.status == SyllabusStatus.UNCERTAIN
    assert any("UNCERTAIN" in x or "evidence" in x.lower() for x in result.validation_issues)


def test_syllabus_uncertain_without_syllabus(tmp_path, lexical_embedder):
    kb = KnowledgeBase(index_dir=tmp_path / "kb", embedder=lexical_embedder)
    result = classify_syllabus(_q(), kb, llm=None, syllabus_present=False)
    assert result.status == SyllabusStatus.UNCERTAIN
    assert "No official syllabus" in result.reason


def test_syllabus_heuristic_with_index(tmp_path, lexical_embedder, sample_docs):
    kb = KnowledgeBase(index_dir=tmp_path / "kb2", embedder=lexical_embedder)
    path = Path(sample_docs["fixtures"]) / "syllabus.docx"
    doc = extract_document(path, "syllabus.docx", DocumentCategory.SYLLABUS, sha256_bytes(path.read_bytes()))
    kb.add_document(doc, skip_if_unchanged=False)
    inn = classify_syllabus(_q(text="State De Morgan's theorems"), kb, llm=None, syllabus_present=True)
    assert inn.status in {SyllabusStatus.IN, SyllabusStatus.UNCERTAIN}
    assert inn.evidence or inn.status == SyllabusStatus.UNCERTAIN
    out = classify_syllabus(
        _q(qid="3", text="Explain quantum annealing optimisation SAT"),
        kb,
        llm=None,
        syllabus_present=True,
    )
    assert out.status in {SyllabusStatus.UNCERTAIN, SyllabusStatus.OUT, SyllabusStatus.PARTIAL}


def test_faculty_edit_and_approval_status():
    result = _result()
    result.approved = True
    paper = QuestionPaper(subject_name="DLD", subject_code="CS301", questions=[_q()], printed_total_marks=5)
    scheme = validate_scheme(paper, [result])
    ok, reason = can_approve_scheme(scheme)
    assert ok, reason
    result.approved = False
    scheme = validate_scheme(paper, [result])
    ok, _ = can_approve_scheme(scheme)
    assert not ok
    assert scheme.approval_status != ApprovalStatus.APPROVED or not result.approved


def test_export_docx_pdf_csv(tmp_path):
    result = _result()
    paper = QuestionPaper(subject_name="DLD", subject_code="CS301", questions=[_q()], printed_total_marks=5)
    scheme = validate_scheme(paper, [result])
    scheme.job_id = "testjob"
    docx_path = export_docx(paper, scheme, tmp_path / "s.docx")
    pdf_path = export_pdf(paper, scheme, tmp_path / "s.pdf")
    csv_path = export_csv(scheme, tmp_path / "s.csv")
    assert docx_path.exists() and docx_path.stat().st_size > 100
    assert pdf_path.exists() and pdf_path.stat().st_size > 100
    text = csv_path.read_text(encoding="utf-8")
    assert "1" in text
    from docx import Document as DocxDocument

    raw = docx_path.read_bytes()
    assert b"C:\\\\Users" not in raw
    paragraphs = "\n".join(p.text for p in DocxDocument(str(docx_path)).paragraphs)
    assert "DRAFT" in paragraphs or "FACULTY" in paragraphs
