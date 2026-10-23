from __future__ import annotations

import streamlit as st

import config
from database import db
from models.schemas import DocumentCategory
from services.document_processor import extract_document, tesseract_status
from services.retrieval_service import get_knowledge_base
from services.security_service import sha256_bytes, store_upload, validate_upload
from services.workflow_orchestrator import new_job_id
from ui.styles import hero, inject


def render() -> None:
    inject()
    hero("Knowledge base", "Local FAISS/NumPy index of syllabus, textbooks and notes.")
    kb = get_knowledge_base()
    stats = kb.stats()
    st.write(
        f"Chunks: **{stats['chunk_count']}** · Documents: **{stats['documents']}** · Backend: `{stats['backend']}`"
    )
    st.json(stats.get("types") or {})

    st.subheader("Indexed documents")
    rows = db.list_kb_documents()
    if not rows:
        st.info("No indexed documents yet.")
    for row in rows:
        cols = st.columns([3, 2, 1, 1])
        cols[0].write(row["filename"])
        cols[1].write(row["category"])
        cols[2].write(row["chunk_count"])
        if cols[3].button("Remove", key=f"rm-{row['id']}"):
            kb.remove_by_hash(row["sha256"])
            st.rerun()

    st.subheader("Inspect retrieval")
    query = st.text_input("Query")
    dtype = st.multiselect(
        "Filter by type",
        [c.value for c in DocumentCategory if c != DocumentCategory.QUESTION_PAPER],
    )
    if st.button("Search") and query.strip():
        hits = kb.search(query, document_types=dtype or None)
        if not hits:
            st.warning("No passages above the similarity threshold.")
        for hit in hits:
            with st.expander(f"{hit.chunk.filename} p.{hit.chunk.page_number} · score {hit.score:.3f}"):
                st.write(hit.chunk.text)

    st.subheader("Add documents to the knowledge base")
    category = st.selectbox(
        "Category",
        [
            DocumentCategory.SYLLABUS.value,
            DocumentCategory.TEXTBOOK.value,
            DocumentCategory.STUDY_MATERIAL.value,
            DocumentCategory.PREVIOUS_SCHEME.value,
        ],
    )
    ocr_info = tesseract_status()
    if not ocr_info["available"]:
        st.caption("Photos and photo-PDFs need Tesseract OCR. It is not currently available.")
    files = st.file_uploader(
        "Files (PDF, DOCX, or images)",
        type=config.UPLOAD_FILE_TYPES,
        accept_multiple_files=True,
        key="kb-up",
    )
    if st.button("Index uploaded files") and files:
        job_id = "kb_" + new_job_id()
        for fh in files:
            err = validate_upload(fh.name, fh.getvalue())
            if err:
                st.error(f"{fh.name}: {err}")
                continue
            data = fh.getvalue()
            path = store_upload(fh.name, data, job_id)
            doc = extract_document(
                path,
                fh.name,
                DocumentCategory(category),
                sha256_bytes(data),
                allow_ocr=True,
            )
            if doc.empty:
                st.error(f"{fh.name}: {doc.extraction_error or 'empty'}")
                continue
            result = kb.add_document(doc)
            st.write(result)

    st.subheader("Maintenance")
    if st.button("Rebuild index from stored KB metadata"):
        st.info(
            "Rebuild walks currently stored index vectors. To fully re-extract, re-upload documents."
        )
        kb.persist()
        st.success("Index metadata rewritten.")

    confirm = st.text_input("Type CLEAR to wipe the knowledge base")
    if st.button("Clear knowledge base", type="secondary"):
        if confirm.strip() == "CLEAR":
            kb.clear()
            st.success("Knowledge base cleared.")
            st.rerun()
        else:
            st.error("Confirmation text did not match CLEAR.")
