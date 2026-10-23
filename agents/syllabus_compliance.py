"""Syllabus coverage using retrieved syllabus passages plus local LLM."""

from __future__ import annotations

from pydantic import BaseModel, Field

from models.schemas import (
    SourceEvidence,
    SubQuestion,
    SyllabusClassification,
    SyllabusStatus,
)
from services.ollama_service import OllamaService
from services.retrieval_service import KnowledgeBase
from services.security_service import wrap_untrusted_text


class _LLMSyllabus(BaseModel):
    status: str = "UNCERTAIN"
    unit: str = ""
    topic: str = ""
    reason: str = ""
    quote_used: str = ""


ALLOWED = {s.value for s in SyllabusStatus}


def classify_syllabus(
    question: SubQuestion,
    kb: KnowledgeBase,
    llm: OllamaService | None,
    syllabus_present: bool,
) -> SyllabusClassification:
    if not syllabus_present:
        return SyllabusClassification(
            status=SyllabusStatus.UNCERTAIN,
            reason="No official syllabus document is available. Definitive IN/OUT claims are not made.",
            needs_faculty_review=True,
            confidence=0.0,
        )
    hits = kb.search(
        question.text,
        document_types=["syllabus"],
        min_score=0.18,
    )
    evidence = kb.as_evidence(hits)
    if not hits:
        return SyllabusClassification(
            status=SyllabusStatus.UNCERTAIN,
            reason="No sufficiently similar syllabus passage was retrieved. Classification is uncertain.",
            evidence=[],
            needs_faculty_review=True,
            confidence=0.15,
        )
    if llm is None:
        top = hits[0]
        status = SyllabusStatus.IN if top.score >= 0.55 else SyllabusStatus.UNCERTAIN
        return SyllabusClassification(
            status=status,
            unit=top.chunk.syllabus_unit,
            topic=top.chunk.section,
            reason="Heuristic similarity to retrieved syllabus text; local LLM was unavailable.",
            evidence=evidence,
            needs_faculty_review=True,
            confidence=min(0.7, top.score),
        )

    evidence_block = "\n\n".join(
        f"[{h.chunk.filename} p.{h.chunk.page_number}] {h.chunk.text[:700]}" for h in hits
    )
    prompt = (
        "Classify syllabus coverage for the exam question using ONLY the syllabus passages.\n"
        "Labels: IN (clearly covered), PARTIAL (only part covered), OUT (demonstrably outside "
        "the supplied syllabus), UNCERTAIN (insufficient/ambiguous evidence).\n"
        "Do not mark OUT merely because wording differs. Equivalent terms and prerequisites can be IN.\n"
        "quote_used must be copied verbatim from a provided passage, or left empty.\n"
        + wrap_untrusted_text("question", f"{question.display_number}: {question.text}")
        + "\n"
        + wrap_untrusted_text("syllabus_passages", evidence_block, limit=2500)
        + '\nSchema: {"status": "IN|PARTIAL|OUT|UNCERTAIN", "unit": str, "topic": str, '
        '"reason": str, "quote_used": str}'
    )
    try:
        parsed = llm.generate_json(prompt, _LLMSyllabus)
        status_raw = parsed.status.upper()
        status = SyllabusStatus(status_raw) if status_raw in ALLOWED else SyllabusStatus.UNCERTAIN
    except Exception as exc:  # noqa: BLE001
        return SyllabusClassification(
            status=SyllabusStatus.UNCERTAIN,
            reason=f"Classifier failed ({type(exc).__name__}); flagged for review.",
            evidence=evidence,
            needs_faculty_review=True,
            confidence=0.2,
        )

    quote = (parsed.quote_used or "").strip()
    verified_quote = False
    if quote:
        verified_quote = any(quote.lower() in h.chunk.text.lower() for h in hits)
        if not verified_quote:
            status = SyllabusStatus.UNCERTAIN if status == SyllabusStatus.OUT else status
    if status == SyllabusStatus.OUT and hits[0].score >= 0.6:
        status = SyllabusStatus.PARTIAL
    needs_review = status in {SyllabusStatus.OUT, SyllabusStatus.PARTIAL, SyllabusStatus.UNCERTAIN}
    selected = []
    for ev in evidence:
        if quote and verified_quote and quote.lower() in ev.quote.lower():
            ev = ev.model_copy(update={"quote": quote, "verified": True})
        selected.append(ev)
    return SyllabusClassification(
        status=status,
        unit=parsed.unit or hits[0].chunk.syllabus_unit,
        topic=parsed.topic or hits[0].chunk.section,
        reason=parsed.reason,
        evidence=selected[:5],
        needs_faculty_review=needs_review,
        confidence=0.75 if status == SyllabusStatus.IN and hits[0].score >= 0.4 else 0.45,
    )
