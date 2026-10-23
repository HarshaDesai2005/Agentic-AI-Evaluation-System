"""Stateful evaluation workflow without a heavyweight agent framework."""

from __future__ import annotations

import json
import uuid
from typing import Any, Callable, Optional

from agents.mark_allocation import allocate_marks
from agents.question_analysis import analyze_question
from agents.solution_generation import generate_solution
from agents.syllabus_compliance import classify_syllabus
from agents.validation import validate_question, validate_scheme
from database import db
from models.schemas import (
    ApprovalStatus,
    DocumentCategory,
    QuestionPaper,
    QuestionResult,
    SubQuestion,
)
from services.logging_config import logger
from services.ollama_service import OllamaService, OllamaUnavailable, get_ollama
from services.retrieval_service import KnowledgeBase, get_knowledge_base


ProgressCb = Callable[[str], None]


def process_question(
    job_id: str,
    question: SubQuestion,
    paper: QuestionPaper,
    kb: KnowledgeBase,
    llm: OllamaService,
    syllabus_present: bool,
) -> QuestionResult:
    result = QuestionResult(
        question_id=question.id,
        display_number=question.display_number,
        question_text=question.text,
        marks=question.marks,
        status="running",
    )
    try:
        result.analysis = analyze_question(question, llm)
        result.syllabus = classify_syllabus(question, kb, llm, syllabus_present)
        result.solution = generate_solution(question, result.analysis, kb, llm)
        result.marking_criteria = allocate_marks(
            question, result.analysis, result.solution, llm
        )
        validate_question(result)
        result.original_generated = result.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        logger.info("Question %s failed: %s", question.display_number, type(exc).__name__)
        result.status = "failed"
        result.validation_issues.append(f"Generation failed: {exc}")
    _store_result(job_id, result)
    return result


def run_job(
    job_id: str,
    paper: QuestionPaper,
    only_question_id: Optional[str] = None,
    progress: Optional[ProgressCb] = None,
) -> dict[str, Any]:
    def report(msg: str) -> None:
        if progress:
            progress(msg)

    llm = get_ollama()
    try:
        llm.ensure_ready()
    except OllamaUnavailable as exc:
        db.update_job(job_id, status="failed", error=str(exc))
        raise

    kb = get_knowledge_base()
    docs = db.list_documents(job_id)
    syllabus_present = any(d["category"] == DocumentCategory.SYLLABUS.value for d in docs)
    db.update_job(job_id, status="running", error=None)

    targets = paper.questions
    if only_question_id:
        targets = [q for q in paper.questions if q.id == only_question_id]
        if not targets:
            raise ValueError("Unknown question id for retry.")

    results_map = {r["question_id"]: r for r in db.list_results(job_id)}
    produced: list[QuestionResult] = []
    for idx, question in enumerate(targets, start=1):
        report(f"Processing {question.display_number} ({idx}/{len(targets)})")
        if question.marks is None or not question.marks_confirmed:
            result = QuestionResult(
                question_id=question.id,
                display_number=question.display_number,
                question_text=question.text,
                marks=question.marks,
                status="needs_review",
                validation_issues=["Marks are not confirmed; generation skipped."],
            )
            _store_result(job_id, result)
            produced.append(result)
            continue
        produced.append(
            process_question(job_id, question, paper, kb, llm, syllabus_present)
        )

    if only_question_id:
        all_results = []
        updated = {r.question_id: r for r in produced}
        for row in db.list_results(job_id):
            qid = row["question_id"]
            if qid in updated:
                all_results.append(updated[qid])
            else:
                payload = json.loads(row.get("reviewed_json") or row["generated_json"])
                all_results.append(QuestionResult.model_validate(payload))
        produced = all_results

    scheme = validate_scheme(paper, produced)
    scheme.job_id = job_id
    status = "needs_review"
    if scheme.all_questions_covered and not any(
        r.status in {"failed", "needs_review", "pending"} for r in produced
    ):
        status = "completed"
    db.update_job(
        job_id,
        status=status,
        approval_status=scheme.approval_status.value,
        paper_total_marks=paper.printed_total_marks,
        attempt_total_marks=scheme.attempt_total_marks,
    )
    report("Workflow finished.")
    return {"scheme": scheme, "status": status}


def _store_result(job_id: str, result: QuestionResult) -> None:
    payload = result.model_dump(mode="json")
    db.upsert_result(
        {
            "id": result.question_id,
            "job_id": job_id,
            "question_id": result.question_id,
            "generated_json": json.dumps(result.original_generated or payload),
            "reviewed_json": json.dumps(payload) if result.reviewed else None,
            "status": result.status,
            "faculty_comment": result.faculty_comment,
            "approved": result.approved,
            "error": "; ".join(result.validation_issues) if result.status == "failed" else None,
        }
    )


def load_scheme(job_id: str) -> Optional[dict[str, Any]]:
    job = db.get_job(job_id)
    if not job:
        return None
    questions = [SubQuestion.model_validate(q) for q in db.load_questions(job_id)]
    paper = QuestionPaper(
        subject_name=job["subject_name"],
        subject_code=job["subject_code"],
        questions=questions,
        printed_total_marks=job.get("paper_total_marks"),
    )
    results: list[QuestionResult] = []
    for row in db.list_results(job_id):
        raw = row.get("reviewed_json") or row["generated_json"]
        item = QuestionResult.model_validate(json.loads(raw))
        item.approved = bool(row["approved"])
        item.faculty_comment = row.get("faculty_comment") or ""
        item.reviewed = bool(row.get("reviewed_json"))
        results.append(item)
    scheme = validate_scheme(paper, results)
    scheme.job_id = job_id
    scheme.approval_status = ApprovalStatus(job.get("approval_status") or "unreviewed")
    return {"job": job, "paper": paper, "scheme": scheme}


def apply_faculty_edit(
    job_id: str,
    question_id: str,
    solution_text: Optional[str],
    criteria: list[dict[str, Any]],
    syllabus_status: Optional[str],
    comment: str,
    approved: bool,
    rejected: bool,
) -> QuestionResult:
    from models.schemas import MarkingCriterion, SyllabusStatus

    row = next((r for r in db.list_results(job_id) if r["question_id"] == question_id), None)
    if not row:
        raise ValueError("Result not found.")
    original = json.loads(row["generated_json"])
    current = json.loads(row.get("reviewed_json") or row["generated_json"])
    result = QuestionResult.model_validate(current)
    result.original_generated = original
    if solution_text is not None and result.solution:
        result.solution.solution_text = solution_text
    if criteria:
        result.marking_criteria = [MarkingCriterion.model_validate(c) for c in criteria]
    if syllabus_status and result.syllabus:
        result.syllabus.status = SyllabusStatus(syllabus_status)
        result.syllabus.needs_faculty_review = syllabus_status != "IN"
    result.faculty_comment = comment
    result.approved = bool(approved) and not rejected
    result.reviewed = True
    if rejected:
        result.approved = False
        result.status = "rejected"
    validate_question(result)
    if result.approved and result.validation_issues:
        result.approved = False
        result.validation_issues.append("Approval blocked until validation issues are resolved.")
    db.upsert_result(
        {
            "id": result.question_id,
            "job_id": job_id,
            "question_id": result.question_id,
            "generated_json": json.dumps(original),
            "reviewed_json": json.dumps(result.model_dump(mode="json")),
            "status": result.status if not rejected else "rejected",
            "faculty_comment": comment,
            "approved": result.approved,
            "error": None,
        }
    )
    return result


def new_job_id() -> str:
    return uuid.uuid4().hex[:12]
