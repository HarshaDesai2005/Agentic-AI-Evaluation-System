"""Deterministic question-paper parser for common engineering formats."""

from __future__ import annotations

import re
import uuid
from typing import Optional

from models.schemas import ExtractedDocument, QuestionPaper, SubQuestion

TOTAL_RE = re.compile(
    r"(?:maximum\s+marks|max\.?\s*marks|total\s+marks)\s*[:\-]?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
PART_RE = re.compile(r"^\s*(part\s*[-]?\s*[a-z]|section\s*[-]?\s*[a-z0-9]+)\b", re.I)
Q_START_RE = re.compile(
    r"^\s*(?:q(?:uestion)?\s*[.\)]?\s*)?(\d{1,2})\s*(?:[.)]|)\s*(.*)$",
    re.IGNORECASE,
)
SUB_RE = re.compile(
    r"^\s*\(\s*([a-z]|[ivx]+|\d+)\s*\)\s*(.*)$",
    re.IGNORECASE,
)
NESTED_SUB_RE = re.compile(
    r"^\s*\(\s*([ivx]+|\d+)\s*\)\s*(.*)$",
    re.IGNORECASE,
)
MARKS_RE = re.compile(
    r"[\(\[]\s*(\d+(?:\.\d+)?)\s*(?:marks?|m)?\s*[\)\]]|\b(\d+(?:\.\d+)?)\s*marks?\b",
    re.IGNORECASE,
)
OR_RE = re.compile(r"^\s*(?:or|internal\s+choice)\s*$", re.IGNORECASE)
ANY_N_RE = re.compile(r"answer\s+any\s+(\w+|\d+)", re.IGNORECASE)
CHOICE_HINT_RE = re.compile(r"attempt\s+any|answer\s+any|either\s+or", re.IGNORECASE)


def parse_question_paper(
    document: ExtractedDocument,
    subject_name: str,
    subject_code: str,
) -> QuestionPaper:
    lines = _numbered_lines(document)
    instructions: list[str] = []
    questions: list[SubQuestion] = []
    warnings: list[str] = []
    current_section: Optional[str] = None
    current_q: Optional[str] = None
    current_sub: Optional[str] = None
    choice_group: Optional[str] = None
    pending_or = False
    buffer: list[str] = []
    buffer_page: Optional[int] = None
    buffer_meta: dict = {}

    def flush() -> None:
        nonlocal buffer, buffer_page, buffer_meta, pending_or
        if not buffer or not current_q:
            buffer = []
            return
        text = " ".join(buffer).strip()
        text, marks, ambiguous = _extract_marks(text)
        notes = []
        if marks is None:
            notes.append("Marks were not found in the extracted text.")
            ambiguous = True
        if pending_or:
            notes.append("Internal choice (OR) alternative.")
        display = current_q if not current_sub else f"{current_q}({current_sub})"
        qid = str(uuid.uuid4())
        questions.append(
            SubQuestion(
                id=qid,
                question_number=current_q,
                subquestion_number=current_sub,
                display_number=display,
                text=text,
                marks=marks,
                marks_confirmed=marks is not None and not ambiguous,
                marks_ambiguous=ambiguous or marks is None,
                section=current_section,
                instructions=buffer_meta.get("instructions"),
                page_number=buffer_page,
                parse_confidence=0.86 if marks is not None else 0.45,
                parse_notes=notes,
                choice_group=choice_group,
                is_internal_choice=bool(choice_group),
                choice_label=buffer_meta.get("choice_label"),
            )
        )
        buffer = []
        pending_or = False

    for page_number, line in lines:
        raw = line.strip()
        if not raw:
            continue
        part_match = PART_RE.match(raw)
        if part_match:
            flush()
            current_section = part_match.group(1).title()
            continue
        if OR_RE.match(raw):
            flush()
            pending_or = True
            if current_q:
                choice_group = f"Q{current_q}"
                if questions and questions[-1].question_number == current_q:
                    questions[-1] = questions[-1].model_copy(
                        update={"choice_group": choice_group, "is_internal_choice": True}
                    )
            continue
        q_match = Q_START_RE.match(raw)
        sub_match = SUB_RE.match(raw)
        if q_match and _looks_like_question_start(raw, q_match):
            flush()
            current_q = q_match.group(1)
            rest = q_match.group(2).strip()
            current_sub = None
            choice_group = None
            pending_or = False
            nested = SUB_RE.match(rest)
            if nested:
                current_sub = nested.group(1).lower()
                rest = nested.group(2).strip()
            if rest and (ANY_N_RE.search(rest) or CHOICE_HINT_RE.search(rest)) and not nested:
                instructions.append(raw)
                buffer = []
                buffer_page = page_number
                buffer_meta = {"choice_label": None, "instructions": rest}
                continue
            buffer = [rest] if rest else []
            buffer_page = page_number
            buffer_meta = {"choice_label": None}
            continue
        if ANY_N_RE.search(raw) or CHOICE_HINT_RE.search(raw):
            instructions.append(raw)
            continue
        if sub_match and current_q:
            flush()
            current_sub = sub_match.group(1).lower()
            rest = sub_match.group(2).strip()
            label = None
            if pending_or or choice_group:
                choice_group = choice_group or f"Q{current_q}"
                label = current_sub
            buffer = [rest] if rest else []
            buffer_page = page_number
            buffer_meta = {"choice_label": label}
            pending_or = False
            continue
        if not current_q:
            instructions.append(raw)
            continue
        buffer.append(raw)
        if buffer_page is None:
            buffer_page = page_number
    flush()

    printed_total = _find_total(document.full_text)
    if not questions:
        warnings.append("No numbered questions could be parsed. Confirm the paper format.")
    missing_marks = [q.display_number for q in questions if q.marks is None]
    if missing_marks:
        warnings.append(
            "Marks are missing or ambiguous for: " + ", ".join(missing_marks)
        )
        warnings.append("Confirm marks before generating a scheme. Marks are never invented.")
    if any(q.is_internal_choice for q in questions):
        warnings.append(
            "Internal choice detected. Paper maximum marks may differ from marks a student answers."
        )

    return QuestionPaper(
        subject_name=subject_name,
        subject_code=subject_code,
        instructions=instructions[:20],
        questions=questions,
        printed_total_marks=printed_total,
        parse_warnings=warnings,
    )


def _numbered_lines(document: ExtractedDocument) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for page in document.pages:
        for line in page.text.splitlines():
            out.append((page.page_number, line))
    if not out and document.full_text:
        for line in document.full_text.splitlines():
            out.append((1, line))
    return out


def _looks_like_question_start(raw: str, match: re.Match) -> bool:
    rest = match.group(2).strip()
    prefix = raw.strip()[:12].lower()
    if prefix.startswith("q") or prefix.startswith("question"):
        return True
    if rest.startswith("("):
        return True
    if MARKS_RE.search(raw):
        return True
    # Avoid treating "2024" or syllabus numbering as questions
    number = match.group(1)
    if len(number) > 2:
        return False
    return bool(rest) and not rest[0].isdigit()


def _extract_marks(text: str) -> tuple[str, Optional[float], bool]:
    matches = list(MARKS_RE.finditer(text))
    if not matches:
        return text.strip(), None, True
    values = []
    for m in matches:
        raw = m.group(1) or m.group(2)
        if raw:
            values.append(float(raw))
    unique = sorted(set(values))
    ambiguous = len(unique) > 1
    marks = unique[-1] if unique else None
    cleaned = MARKS_RE.sub("", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" :-")
    return cleaned, marks, ambiguous


def _find_total(text: str) -> Optional[float]:
    match = TOTAL_RE.search(text or "")
    if not match:
        return None
    return float(match.group(1))


def apply_confirmed_marks(
    paper: QuestionPaper, marks_by_id: dict[str, float]
) -> QuestionPaper:
    updated = []
    for q in paper.questions:
        if q.id in marks_by_id:
            value = float(marks_by_id[q.id])
            q = q.model_copy(
                update={
                    "marks": value,
                    "marks_confirmed": True,
                    "marks_ambiguous": False,
                    "parse_notes": [
                        n for n in q.parse_notes if "Marks were not found" not in n
                    ]
                    + ["Marks confirmed by user."],
                    "parse_confidence": max(q.parse_confidence, 0.9),
                }
            )
        updated.append(q)
    return paper.model_copy(update={"questions": updated})
