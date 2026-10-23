"""Deterministic validation. Never trust another agent for arithmetic."""

from __future__ import annotations

from models.schemas import (
    ApprovalStatus,
    EvaluationScheme,
    QuestionPaper,
    QuestionResult,
    SyllabusStatus,
    ValidationIssue,
)


def criterion_sum(criteria) -> float:
    return round(sum(float(c.marks) for c in criteria), 2)


def marks_agree(allocated: float, expected: float | None, tol: float = 0.051) -> bool:
    if expected is None:
        return False
    return abs(allocated - float(expected)) < tol


def validate_question(result: QuestionResult) -> list[str]:
    issues: list[str] = []
    if not result.question_text.strip():
        issues.append("Question text is empty.")
    if result.marks is None:
        issues.append("Marks are not confirmed.")
    if not result.solution or not result.solution.solution_text.strip():
        issues.append("Solution is missing.")
    if not result.marking_criteria:
        issues.append("Marking criteria are missing.")
    allocated = criterion_sum(result.marking_criteria)
    result.allocated_marks_sum = allocated
    result.marks_match = marks_agree(allocated, result.marks)
    if result.marks is not None and not result.marks_match:
        issues.append(
            f"Marking components sum to {allocated}, not the question marks {result.marks}."
        )
    if result.syllabus is None:
        issues.append("Syllabus classification is missing.")
    else:
        if result.syllabus.status in {SyllabusStatus.OUT, SyllabusStatus.UNCERTAIN}:
            issues.append(f"Syllabus status is {result.syllabus.status.value} and needs review.")
        if result.syllabus.status != SyllabusStatus.UNCERTAIN and not any(
            e.verified for e in result.syllabus.evidence
        ):
            issues.append("Syllabus classification lacks verified source evidence.")
            if result.syllabus.status == SyllabusStatus.OUT:
                result.syllabus.status = SyllabusStatus.UNCERTAIN
                result.syllabus.needs_faculty_review = True
                issues.append("OUT without evidence was downgraded to UNCERTAIN.")
    if result.solution and result.solution.insufficient_evidence:
        issues.append("Insufficient supporting document evidence for the generated solution.")
    if result.solution:
        for ev in result.solution.evidence:
            if ev.quote and ev.filename and ev.filename.startswith("("):
                continue
    result.validation_issues = issues
    if issues:
        result.status = "needs_review"
        result.confidence = min(result.confidence, 0.4)
    else:
        result.status = "validated"
        result.confidence = max(result.confidence, 0.7)
    return issues


def validate_scheme(paper: QuestionPaper, results: list[QuestionResult]) -> EvaluationScheme:
    issues: list[ValidationIssue] = []
    paper_ids = [q.id for q in paper.questions]
    result_ids = [r.question_id for r in results]
    missing = [qid for qid in paper_ids if qid not in result_ids]
    extra = [qid for qid in result_ids if qid not in paper_ids]
    if missing:
        issues.append(
            ValidationIssue(
                severity="error",
                message=f"Missing results for {len(missing)} question(s).",
            )
        )
    if extra:
        issues.append(
            ValidationIssue(severity="warning", message="Unexpected extra question results found.")
        )
    seen = set()
    for q in paper.questions:
        key = (q.question_number, q.subquestion_number, q.text[:80])
        if key in seen:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    question_id=q.id,
                    message=f"Possible duplicate question {q.display_number}.",
                )
            )
        seen.add(key)
    for result in results:
        for msg in validate_question(result):
            issues.append(
                ValidationIssue(severity="warning", question_id=result.question_id, message=msg)
            )

    scheme_total = round(sum(r.allocated_marks_sum for r in results), 2)
    choice_groups: dict[str, list[QuestionResult]] = {}
    for q, r in _paired(paper, results):
        if q.choice_group:
            choice_groups.setdefault(q.choice_group, []).append(r)

    attempt_total = 0.0
    accounted = set()
    for q, r in _paired(paper, results):
        if q.id in accounted:
            continue
        if q.choice_group and q.choice_group in choice_groups:
            group = choice_groups[q.choice_group]
            attempt_total += max((x.marks or 0.0) for x in group)
            for item in group:
                accounted.add(item.question_id)
        else:
            attempt_total += float(q.marks or 0.0)
            accounted.add(q.id)
    attempt_total = round(attempt_total, 2)

    if paper.printed_total_marks is not None:
        paper_sum = round(sum(q.marks or 0.0 for q in paper.questions), 2)
        if abs(paper_sum - paper.printed_total_marks) > 0.051 and not choice_groups:
            issues.append(
                ValidationIssue(
                    severity="error",
                    message=(
                        f"Sum of question marks ({paper_sum}) does not match printed total "
                        f"({paper.printed_total_marks}). Automatic approval is blocked."
                    ),
                )
            )

    approval = ApprovalStatus.PENDING_REVIEW
    blocking = [i for i in issues if i.severity == "error"]
    needs = any(r.status == "needs_review" or not r.approved for r in results)
    if blocking or needs:
        approval = ApprovalStatus.PENDING_REVIEW
    if results and all(r.approved for r in results) and not blocking:
        approval = ApprovalStatus.APPROVED

    return EvaluationScheme(
        job_id="",
        subject_name=paper.subject_name,
        subject_code=paper.subject_code,
        questions=results,
        issues=issues,
        paper_total_marks=paper.printed_total_marks,
        scheme_total_marks=scheme_total,
        attempt_total_marks=attempt_total,
        approval_status=approval,
        all_questions_covered=not missing,
    )


def _paired(paper: QuestionPaper, results: list[QuestionResult]):
    by_id = {r.question_id: r for r in results}
    for q in paper.questions:
        if q.id in by_id:
            yield q, by_id[q.id]


def can_approve_scheme(scheme: EvaluationScheme) -> tuple[bool, str]:
    if not scheme.all_questions_covered:
        return False, "Not every parsed question has a result."
    if any(i.severity == "error" for i in scheme.issues):
        return False, "Resolve validation errors before whole-scheme approval."
    if not scheme.questions:
        return False, "No questions to approve."
    if not all(q.approved for q in scheme.questions):
        return False, "Every question must be individually approved first."
    mismatched = [q.display_number for q in scheme.questions if not q.marks_match]
    if mismatched:
        return False, "Mark totals do not match for: " + ", ".join(mismatched)
    return True, "Validation checks passed."
