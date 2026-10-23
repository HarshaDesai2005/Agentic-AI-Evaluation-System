"""Generate exam solutions from retrieved local evidence."""

from __future__ import annotations

from pydantic import BaseModel, Field

from models.schemas import (
    EvidenceKind,
    GeneratedSolution,
    QuestionAnalysis,
    SourceEvidence,
    SubQuestion,
)
from services.ollama_service import OllamaService
from services.retrieval_service import KnowledgeBase, supporting_types
from services.security_service import wrap_untrusted_text


class _LLMSolution(BaseModel):
    solution_text: str = ""
    key_points: list[str] = Field(default_factory=list)
    used_model_knowledge: bool = False
    insufficient_evidence: bool = False
    warnings: list[str] = Field(default_factory=list)


def generate_solution(
    question: SubQuestion,
    analysis: QuestionAnalysis,
    kb: KnowledgeBase,
    llm: OllamaService,
) -> GeneratedSolution:
    hits = kb.search(
        f"{question.text} {analysis.topic}".strip(),
        document_types=supporting_types(),
    )
    evidence = kb.as_evidence(hits)
    if not hits:
        # Still generate, but mark insufficient evidence clearly.
        evidence_block = "No supporting textbook/notes passages met the similarity threshold."
        insufficient = True
    else:
        evidence_block = "\n\n".join(
            f"[{h.chunk.filename} p.{h.chunk.page_number} score={h.score:.2f}]\n{h.chunk.text[:800]}"
            for h in hits
        )
        insufficient = False

    prompt = (
        "Write an exam-appropriate solution for this engineering question.\n"
        "Use the supporting passages when they are relevant. Distinguish document evidence "
        "from your general knowledge. Do not invent quotations, page numbers, or sources.\n"
        "Preserve formulas and technical notation in plain text.\n"
        "If evidence is weak, set insufficient_evidence=true and say what is missing.\n"
        f"Question type: {analysis.question_type.value}. Expected format: {analysis.expected_format}\n"
        f"Marks: {question.marks}\n"
        + wrap_untrusted_text("question", f"{question.display_number}: {question.text}")
        + "\n"
        + wrap_untrusted_text("supporting_passages", evidence_block, limit=2800)
        + '\nSchema: {"solution_text": str, "key_points": [str], "used_model_knowledge": bool, '
        '"insufficient_evidence": bool, "warnings": [str]}'
    )
    parsed = llm.generate_json(prompt, _LLMSolution)
    warnings = list(parsed.warnings)
    if insufficient or parsed.insufficient_evidence:
        warnings.append(
            "Insufficient document evidence: parts of this answer may be general model knowledge."
        )
        if not evidence:
            evidence = [
                SourceEvidence(
                    filename="(none retrieved)",
                    quote="No supporting passage met the retrieval threshold.",
                    verified=False,
                    kind=EvidenceKind.INSUFFICIENT,
                )
            ]
    if parsed.used_model_knowledge:
        warnings.append("The model reported using general knowledge in addition to retrieved documents.")
    return GeneratedSolution(
        solution_text=parsed.solution_text.strip(),
        key_points=parsed.key_points,
        evidence=evidence,
        used_model_knowledge=parsed.used_model_knowledge or insufficient,
        insufficient_evidence=insufficient or parsed.insufficient_evidence,
        warnings=warnings,
    )
