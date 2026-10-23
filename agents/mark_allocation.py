"""Mark allocation constrained by printed/confirmed marks."""

from __future__ import annotations

from pydantic import BaseModel, Field

from models.schemas import (
    GeneratedSolution,
    MarkingCriterion,
    QuestionAnalysis,
    QuestionType,
    SubQuestion,
)
from services.ollama_service import OllamaService
from services.security_service import wrap_untrusted_text


class _LLMMarks(BaseModel):
    criteria: list[dict] = Field(default_factory=list)


def allocate_marks(
    question: SubQuestion,
    analysis: QuestionAnalysis,
    solution: GeneratedSolution,
    llm: OllamaService,
) -> list[MarkingCriterion]:
    if question.marks is None:
        raise ValueError("Cannot allocate marks until the question marks are confirmed.")
    total = float(question.marks)
    style = _style_hint(analysis)
    prompt = (
        "Create a step-wise marking scheme for this exam answer.\n"
        f"The component marks MUST sum to exactly {total}. Do not split marks equally unless justified.\n"
        f"{style}\n"
        "Each criterion needs: step_label, expected_answer, marks (number), partial_credit, alternatives.\n"
        + wrap_untrusted_text("question", f"{question.display_number} [{total} marks]: {question.text}")
        + "\n"
        + wrap_untrusted_text("solution", solution.solution_text, limit=1800)
        + "\nKey points: "
        + "; ".join(solution.key_points[:8])
        + '\nSchema: {"criteria": [{"step_label": str, "expected_answer": str, "marks": number, '
        '"partial_credit": str, "alternatives": str}]}'
    )
    parsed = llm.generate_json(prompt, _LLMMarks)
    criteria: list[MarkingCriterion] = []
    for item in parsed.criteria:
        try:
            criteria.append(
                MarkingCriterion(
                    step_label=str(item.get("step_label") or "Step"),
                    expected_answer=str(item.get("expected_answer") or ""),
                    marks=float(item.get("marks") or 0),
                    partial_credit=str(item.get("partial_credit") or ""),
                    alternatives=str(item.get("alternatives") or ""),
                )
            )
        except Exception:
            continue
    if not criteria:
        criteria = _fallback_criteria(analysis, solution, total)
    return criteria


def _style_hint(analysis: QuestionAnalysis) -> str:
    if analysis.question_type == QuestionType.NUMERICAL:
        return (
            "For numerical work, prefer meaningful components such as formula selection, "
            "substitution, intermediate calculation and final answer when they apply. "
            "Do not invent extra steps."
        )
    if analysis.question_type == QuestionType.THEORETICAL:
        return (
            "For theory, allocate marks to distinct concepts, explanations, comparisons, "
            "diagrams or examples actually required by the question."
        )
    if analysis.question_type == QuestionType.DERIVATION:
        return "Allocate marks to setup, key intermediate identities and the final derived result."
    return "Allocate marks only to assessable components present in a correct solution."


def _fallback_criteria(
    analysis: QuestionAnalysis, solution: GeneratedSolution, total: float
) -> list[MarkingCriterion]:
    points = solution.key_points[:4] or ["Correct and complete solution"]
    n = len(points)
    raw = [round(total / n, 2) for _ in points]
    raw[-1] = round(total - sum(raw[:-1]), 2)
    return [
        MarkingCriterion(
            step_label=f"Component {i+1}",
            expected_answer=point,
            marks=marks,
            partial_credit="Award partial credit for incomplete but relevant treatment.",
            alternatives="",
        )
        for i, (point, marks) in enumerate(zip(points, raw))
    ]
