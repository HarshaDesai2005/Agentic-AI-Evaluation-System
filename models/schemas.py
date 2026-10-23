"""Validated data models for papers, schemes, evidence and review."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class DocumentCategory(str, Enum):
    QUESTION_PAPER = "question_paper"
    SYLLABUS = "syllabus"
    TEXTBOOK = "textbook"
    STUDY_MATERIAL = "study_material"
    PREVIOUS_SCHEME = "previous_scheme"


class SyllabusStatus(str, Enum):
    IN = "IN"
    PARTIAL = "PARTIAL"
    OUT = "OUT"
    UNCERTAIN = "UNCERTAIN"


class JobStatus(str, Enum):
    DRAFT = "draft"
    PARSING = "parsing"
    AWAITING_MARKS = "awaiting_marks"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    FAILED = "failed"


class ApprovalStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    PARTIALLY_APPROVED = "partially_approved"
    APPROVED = "faculty_approved"
    REJECTED = "rejected"


class QuestionType(str, Enum):
    NUMERICAL = "numerical"
    THEORETICAL = "theoretical"
    DERIVATION = "derivation"
    COMPARISON = "comparison"
    DIAGRAM = "diagram"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class EvidenceKind(str, Enum):
    DOCUMENT = "document"
    MODEL_KNOWLEDGE = "model_knowledge"
    INSUFFICIENT = "insufficient"


class SourceEvidence(BaseModel):
    filename: str
    document_type: Optional[str] = None
    page_number: Optional[int] = None
    section: Optional[str] = None
    quote: str = ""
    score: Optional[float] = None
    verified: bool = False
    kind: EvidenceKind = EvidenceKind.DOCUMENT


class ExtractedPage(BaseModel):
    page_number: int
    text: str
    heading: Optional[str] = None


class ExtractedDocument(BaseModel):
    original_filename: str
    stored_filename: str
    file_type: str
    category: DocumentCategory
    page_count: int = 0
    pages: list[ExtractedPage] = Field(default_factory=list)
    full_text: str = ""
    headings: list[str] = Field(default_factory=list)
    is_scanned: bool = False
    ocr_used: bool = False
    extraction_status: str = "ok"
    extraction_error: Optional[str] = None
    sha256: str = ""
    empty: bool = False


class TextChunk(BaseModel):
    chunk_id: str
    text: str
    filename: str
    document_type: str
    page_number: Optional[int] = None
    section: Optional[str] = None
    subject: Optional[str] = None
    syllabus_unit: Optional[str] = None
    sha256: str = ""


class SubQuestion(BaseModel):
    id: str
    question_number: str
    subquestion_number: Optional[str] = None
    display_number: str
    text: str
    marks: Optional[float] = None
    marks_confirmed: bool = False
    marks_ambiguous: bool = False
    section: Optional[str] = None
    instructions: Optional[str] = None
    page_number: Optional[int] = None
    parse_confidence: float = 0.7
    parse_notes: list[str] = Field(default_factory=list)
    choice_group: Optional[str] = None
    is_internal_choice: bool = False
    choice_label: Optional[str] = None


class QuestionPaper(BaseModel):
    subject_name: str
    subject_code: str
    title: Optional[str] = None
    instructions: list[str] = Field(default_factory=list)
    questions: list[SubQuestion] = Field(default_factory=list)
    printed_total_marks: Optional[float] = None
    attempt_total_marks: Optional[float] = None
    parse_warnings: list[str] = Field(default_factory=list)


class QuestionAnalysis(BaseModel):
    topic: str = ""
    question_type: QuestionType = QuestionType.UNKNOWN
    expected_format: str = ""
    requires_calculation: bool = False
    requires_derivation: bool = False
    requires_diagram: bool = False
    notes: str = ""


class SyllabusClassification(BaseModel):
    status: SyllabusStatus = SyllabusStatus.UNCERTAIN
    unit: Optional[str] = None
    topic: Optional[str] = None
    reason: str = ""
    evidence: list[SourceEvidence] = Field(default_factory=list)
    needs_faculty_review: bool = True
    confidence: float = 0.0


class MarkingCriterion(BaseModel):
    step_label: str
    expected_answer: str
    marks: float = Field(ge=0)
    partial_credit: str = ""
    alternatives: str = ""

    @field_validator("marks")
    @classmethod
    def round_marks(cls, value: float) -> float:
        return round(float(value), 2)


class GeneratedSolution(BaseModel):
    solution_text: str
    key_points: list[str] = Field(default_factory=list)
    evidence: list[SourceEvidence] = Field(default_factory=list)
    used_model_knowledge: bool = False
    insufficient_evidence: bool = False
    warnings: list[str] = Field(default_factory=list)


class QuestionResult(BaseModel):
    question_id: str
    display_number: str
    question_text: str
    marks: Optional[float] = None
    analysis: Optional[QuestionAnalysis] = None
    syllabus: Optional[SyllabusClassification] = None
    solution: Optional[GeneratedSolution] = None
    marking_criteria: list[MarkingCriterion] = Field(default_factory=list)
    allocated_marks_sum: float = 0.0
    marks_match: bool = False
    validation_issues: list[str] = Field(default_factory=list)
    status: str = "pending"
    confidence: float = 0.0
    faculty_comment: str = ""
    approved: bool = False
    original_generated: Optional[dict[str, Any]] = None
    reviewed: bool = False

    @model_validator(mode="after")
    def compute_sum(self) -> "QuestionResult":
        self.allocated_marks_sum = round(sum(c.marks for c in self.marking_criteria), 2)
        if self.marks is not None:
            self.marks_match = abs(self.allocated_marks_sum - float(self.marks)) < 0.051
        return self


class ValidationIssue(BaseModel):
    severity: str
    question_id: Optional[str] = None
    message: str


class FacultyReview(BaseModel):
    question_id: str
    comment: str = ""
    approved: bool = False
    rejected: bool = False


class EvaluationScheme(BaseModel):
    job_id: str
    subject_name: str
    subject_code: str
    questions: list[QuestionResult] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)
    paper_total_marks: Optional[float] = None
    scheme_total_marks: float = 0.0
    attempt_total_marks: Optional[float] = None
    approval_status: ApprovalStatus = ApprovalStatus.UNREVIEWED
    all_questions_covered: bool = False
