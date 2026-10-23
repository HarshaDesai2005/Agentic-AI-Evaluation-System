"""Question analysis: type, topic and expected answer format."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from models.schemas import QuestionAnalysis, QuestionType, SubQuestion
from services.ollama_service import OllamaService
from services.security_service import wrap_untrusted_text

_CALC = re.compile(
    r"\b(calculate|compute|find|convert|evaluate|determine|simplify|obtain)\b", re.I
)
_DERIV = re.compile(r"\b(derive|derivation|prove|show that)\b", re.I)
_DIAG = re.compile(r"\b(draw|diagram|sketch|circuit|block diagram|k-?map)\b", re.I)
_COMP = re.compile(r"\b(compare|difference|distinguish|versus|vs\.?)\b", re.I)
_THEORY = re.compile(r"\b(explain|describe|discuss|define|state|list|write)\b", re.I)


class _LLMAnalysis(BaseModel):
    topic: str = ""
    question_type: str = "unknown"
    expected_format: str = ""
    requires_calculation: bool = False
    requires_derivation: bool = False
    requires_diagram: bool = False
    notes: str = ""


def heuristic_analysis(question: SubQuestion) -> QuestionAnalysis:
    text = question.text
    qtype = QuestionType.UNKNOWN
    calc = bool(_CALC.search(text) or re.search(r"\d", text) and "convert" in text.lower())
    deriv = bool(_DERIV.search(text))
    diagram = bool(_DIAG.search(text))
    compare = bool(_COMP.search(text))
    theory = bool(_THEORY.search(text))
    if deriv:
        qtype = QuestionType.DERIVATION
    elif diagram and (calc or theory):
        qtype = QuestionType.MIXED
    elif diagram:
        qtype = QuestionType.DIAGRAM
    elif compare:
        qtype = QuestionType.COMPARISON
    elif calc:
        qtype = QuestionType.NUMERICAL
    elif theory:
        qtype = QuestionType.THEORETICAL
    expected = {
        QuestionType.NUMERICAL: "Formula, substitution, calculation and final value.",
        QuestionType.THEORETICAL: "Definitions, explanation and relevant key points.",
        QuestionType.DERIVATION: "Assumptions, stepwise derivation and result.",
        QuestionType.COMPARISON: "Criteria, comparison points and conclusion.",
        QuestionType.DIAGRAM: "Labeled diagram and short explanation.",
        QuestionType.MIXED: "Combination of explanation and working.",
        QuestionType.UNKNOWN: "Exam-style solution covering asked parts.",
    }[qtype]
    return QuestionAnalysis(
        topic="",
        question_type=qtype,
        expected_format=expected,
        requires_calculation=calc or qtype == QuestionType.NUMERICAL,
        requires_derivation=deriv,
        requires_diagram=diagram,
        notes="Heuristic analysis; refined by the local model when available.",
    )


def analyze_question(question: SubQuestion, llm: OllamaService | None) -> QuestionAnalysis:
    base = heuristic_analysis(question)
    if llm is None:
        return base
    prompt = (
        "Analyse this engineering exam question. Identify the topic, type and expected answer format.\n"
        "question_type must be one of: numerical, theoretical, derivation, comparison, diagram, mixed, unknown.\n"
        + wrap_untrusted_text("question", f"{question.display_number}: {question.text}")
        + '\nSchema: {"topic": str, "question_type": str, "expected_format": str, '
        '"requires_calculation": bool, "requires_derivation": bool, '
        '"requires_diagram": bool, "notes": str}'
    )
    try:
        parsed = llm.generate_json(prompt, _LLMAnalysis)
    except Exception:
        return base
    try:
        qtype = QuestionType(parsed.question_type.lower())
    except ValueError:
        qtype = base.question_type
    return QuestionAnalysis(
        topic=parsed.topic or base.topic,
        question_type=qtype,
        expected_format=parsed.expected_format or base.expected_format,
        requires_calculation=parsed.requires_calculation or base.requires_calculation,
        requires_derivation=parsed.requires_derivation or base.requires_derivation,
        requires_diagram=parsed.requires_diagram or base.requires_diagram,
        notes=parsed.notes,
    )
