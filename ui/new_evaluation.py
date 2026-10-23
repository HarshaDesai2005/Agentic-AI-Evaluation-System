from __future__ import annotations

import uuid

import streamlit as st

import config
from database import db
from models.schemas import DocumentCategory, ExtractedDocument, QuestionPaper, SubQuestion
from services.document_processor import (
    extract_document,
    merge_extracted,
    preview_text,
    tesseract_status,
)
from services.question_parser import apply_confirmed_marks, parse_question_paper
from services.retrieval_service import get_knowledge_base
from services.security_service import sha256_bytes, store_upload, validate_upload
from services.workflow_orchestrator import new_job_id, run_job
from ui.styles import hero, inject

CATEGORY_LABELS = {
    DocumentCategory.QUESTION_PAPER: "Question paper",
    DocumentCategory.SYLLABUS: "Official syllabus",
    DocumentCategory.TEXTBOOK: "Textbook",
    DocumentCategory.STUDY_MATERIAL: "Study material / notes",
    DocumentCategory.PREVIOUS_SCHEME: "Previous approved scheme (optional)",
}


def render() -> None:
    inject()
    hero(
        "New evaluation",
        "Upload PDF, DOCX, photos, or photo-PDFs. Confirm questions and marks, then generate.",
    )

    with st.form("meta"):
        c1, c2 = st.columns(2)
        subject_name = c1.text_input("Subject name", value=st.session_state.get("subject_name", "Digital Logic Design"))
        subject_code = c2.text_input("Subject code", value=st.session_state.get("subject_code", "CS301"))
        submitted_meta = st.form_submit_button("Set subject")
    if submitted_meta:
        st.session_state["subject_name"] = subject_name.strip()
        st.session_state["subject_code"] = subject_code.strip()

    subject_name = st.session_state.get("subject_name", subject_name).strip()
    subject_code = st.session_state.get("subject_code", subject_code).strip()
    if not subject_name or not subject_code:
        st.warning("Enter a subject name and code first.")
        return

    st.subheader("Upload documents")
    ocr_info = tesseract_status()
    if ocr_info["available"]:
        st.caption("Tesseract OCR is available for photos and scanned/photo PDFs.")
    else:
        st.warning(
            "Tesseract OCR is not installed. Photos and photo-PDFs cannot be read until you install it."
        )
        with st.expander("Install Tesseract OCR (Windows)", expanded=False):
            st.code(ocr_info["message"])
    allow_ocr = st.checkbox(
        "OCR photos and scanned/photo PDFs (recommended)",
        value=True,
        help="Needs a local Tesseract install. Images always use OCR. Photo-PDFs are OCR'd when a page has almost no text.",
    )
    uploads: dict[DocumentCategory, object] = {}
    uploads[DocumentCategory.QUESTION_PAPER] = st.file_uploader(
        CATEGORY_LABELS[DocumentCategory.QUESTION_PAPER] + " (PDF, DOCX, or one photo per page)",
        type=config.UPLOAD_FILE_TYPES,
        accept_multiple_files=True,
    )
    uploads[DocumentCategory.SYLLABUS] = st.file_uploader(
        CATEGORY_LABELS[DocumentCategory.SYLLABUS],
        type=config.UPLOAD_FILE_TYPES,
        accept_multiple_files=True,
    )
    uploads[DocumentCategory.TEXTBOOK] = st.file_uploader(
        CATEGORY_LABELS[DocumentCategory.TEXTBOOK],
        type=config.UPLOAD_FILE_TYPES,
        accept_multiple_files=True,
    )
    uploads[DocumentCategory.STUDY_MATERIAL] = st.file_uploader(
        CATEGORY_LABELS[DocumentCategory.STUDY_MATERIAL],
        type=config.UPLOAD_FILE_TYPES,
        accept_multiple_files=True,
    )
    uploads[DocumentCategory.PREVIOUS_SCHEME] = st.file_uploader(
        CATEGORY_LABELS[DocumentCategory.PREVIOUS_SCHEME],
        type=config.UPLOAD_FILE_TYPES,
        accept_multiple_files=True,
    )

    if st.button("Extract, index and parse", type="primary"):
        qp_files = _as_files(uploads[DocumentCategory.QUESTION_PAPER])
        if not qp_files:
            st.error("A question paper is required (PDF, DOCX, or photos of the pages).")
            return
        job_id = new_job_id()
        db.create_job(job_id, subject_name, subject_code)
        extracted: dict[str, ExtractedDocument] = {}
        filespecs: list[tuple[DocumentCategory, object]] = []
        for f in qp_files:
            filespecs.append((DocumentCategory.QUESTION_PAPER, f))
        for cat in (
            DocumentCategory.SYLLABUS,
            DocumentCategory.TEXTBOOK,
            DocumentCategory.STUDY_MATERIAL,
            DocumentCategory.PREVIOUS_SCHEME,
        ):
            for f in _as_files(uploads[cat]):
                filespecs.append((cat, f))

        kb = get_knowledge_base()
        progress = st.progress(0)
        for i, (cat, fh) in enumerate(filespecs, start=1):
            try:
                data = fh.getvalue()
                err = validate_upload(fh.name, data)
                if err:
                    st.error(f"{fh.name}: {err}")
                    progress.progress(i / len(filespecs))
                    continue
                path = store_upload(fh.name, data, job_id)
                digest = sha256_bytes(data)
                doc = extract_document(path, fh.name, cat, digest, allow_ocr=allow_ocr)
                extracted[path.name] = doc
                db.insert_document(
                    {
                        "id": str(uuid.uuid4()),
                        "job_id": job_id,
                        "category": cat.value,
                        "original_filename": fh.name,
                        "stored_path": str(path),
                        "sha256": digest,
                        "page_count": doc.page_count,
                        "extraction_status": doc.extraction_status,
                        "is_scanned": doc.is_scanned,
                        "ocr_used": doc.ocr_used,
                        "extracted_preview": preview_text(doc.full_text),
                        "indexed": False,
                    }
                )
                if cat != DocumentCategory.QUESTION_PAPER and not doc.empty:
                    kb.add_document(doc, subject=subject_name)
            except Exception as exc:  # noqa: BLE001 — show extraction failures in the UI
                st.error(f"{getattr(fh, 'name', 'file')}: {type(exc).__name__}: {exc}")
            progress.progress(i / len(filespecs))

        qp_docs = [d for d in extracted.values() if d.category == DocumentCategory.QUESTION_PAPER]
        if not qp_docs:
            st.error("Question paper extraction failed.")
            return
        paper_doc = merge_extracted(qp_docs, original_filename=qp_files[0].name)
        if paper_doc.empty:
            st.error(paper_doc.extraction_error or "Could not read text from the question paper.")
            return
        paper = parse_question_paper(paper_doc, subject_name, subject_code)
        db.save_questions(job_id, [q.model_dump(mode="json") for q in paper.questions])
        db.update_job(
            job_id,
            status="awaiting_marks",
            paper_total_marks=paper.printed_total_marks,
        )
        st.session_state["active_job_id"] = job_id
        st.session_state["parsed_paper"] = paper.model_dump(mode="json")
        st.session_state["extracted_docs"] = {
            k: v.model_dump(mode="json") for k, v in extracted.items()
        }
        st.success(f"Job {job_id}: extracted {len(paper.questions)} question item(s). Confirm marks below.")

    job_id = st.session_state.get("active_job_id")
    extracted_dump = st.session_state.get("extracted_docs")
    paper_dump = st.session_state.get("parsed_paper")
    if not job_id or not paper_dump:
        st.info("Upload files and extract to continue.")
        return

    st.subheader("Extraction preview")
    for name, payload in (extracted_dump or {}).items():
        doc = ExtractedDocument.model_validate(payload)
        with st.expander(f"{doc.original_filename} · {doc.category.value} · {doc.extraction_status}"):
            if doc.extraction_error:
                st.warning(doc.extraction_error)
            if doc.ocr_used:
                st.caption("Text was read with local OCR.")
            elif doc.is_scanned:
                st.warning("This looks like a photo or scan. Install Tesseract if the text is empty.")
            st.text(preview_text(doc.full_text, 1200) or "(empty)")

    paper = QuestionPaper.model_validate(paper_dump)
    st.subheader("Confirm questions and marks")
    for w in paper.parse_warnings:
        st.warning(w)
    if paper.printed_total_marks is not None:
        st.caption(f"Printed total marks found: {paper.printed_total_marks}")

    marks_by_id: dict[str, float] = {}
    for q in paper.questions:
        cols = st.columns([1.2, 5, 1.4])
        cols[0].markdown(f"**{q.display_number}**")
        cols[1].write(q.text)
        default = float(q.marks) if q.marks is not None else 0.0
        value = cols[2].number_input(
            "Marks",
            min_value=0.0,
            step=0.5,
            value=default,
            key=f"marks-{q.id}",
            label_visibility="collapsed",
        )
        marks_by_id[q.id] = float(value)
        notes = []
        if q.marks_ambiguous or q.marks is None:
            notes.append("Needs confirmation")
        if q.is_internal_choice:
            notes.append(f"Internal choice group {q.choice_group}")
        if notes:
            st.caption(" · ".join(notes))

    if st.button("Save confirmed marks"):
        paper = apply_confirmed_marks(paper, marks_by_id)
        db.save_questions(job_id, [q.model_dump(mode="json") for q in paper.questions])
        st.session_state["parsed_paper"] = paper.model_dump(mode="json")
        st.success("Marks saved. Unconfirmed or zero marks will be skipped until you set them.")

    paper = QuestionPaper.model_validate(st.session_state["parsed_paper"])
    unconfirmed = [q.display_number for q in paper.questions if not q.marks_confirmed or q.marks is None]
    if unconfirmed:
        st.error("Confirm marks for: " + ", ".join(unconfirmed))

    if st.button("Start evaluation workflow", disabled=bool(unconfirmed)):
        status = st.empty()
        try:
            outcome = run_job(
                job_id,
                paper,
                progress=lambda m: status.write(m),
            )
            st.session_state["last_scheme"] = outcome["scheme"].model_dump(mode="json")
            st.success("Workflow finished. Open Evaluation Results and Faculty Review.")
            st.session_state["nav"] = "Evaluation Results"
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))


def _as_files(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
