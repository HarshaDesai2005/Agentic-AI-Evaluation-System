from __future__ import annotations

import json

import streamlit as st

from agents.validation import can_approve_scheme
from database import db
from models.schemas import ApprovalStatus, SyllabusStatus
from services.export_service import export_csv, export_docx, export_pdf, export_training_dataset
from services.workflow_orchestrator import apply_faculty_edit, load_scheme
from ui.styles import badge, hero, inject


def render() -> None:
    inject()
    hero(
        "Faculty review",
        "Edit answers and marks, correct syllabus labels, and approve. Unreviewed schemes stay DRAFT.",
    )
    jobs = db.list_jobs(30)
    if not jobs:
        st.info("No jobs yet.")
        return
    labels = {f"{j['subject_code']} · {j['id']} · {j['approval_status']}": j["id"] for j in jobs}
    selected = st.selectbox("Job", list(labels.keys()))
    job_id = labels[selected]
    st.session_state["active_job_id"] = job_id
    payload = load_scheme(job_id)
    if not payload or not payload["scheme"].questions:
        st.warning("Generate results before review.")
        return
    paper = payload["paper"]
    scheme = payload["scheme"]

    st.markdown(
        badge(_label(scheme.approval_status), "ok" if scheme.approval_status == ApprovalStatus.APPROVED else "warn"),
        unsafe_allow_html=True,
    )

    result = st.selectbox(
        "Question",
        scheme.questions,
        format_func=lambda q: f"{q.display_number} ({'approved' if q.approved else q.status})",
    )
    st.write(result.question_text)
    if result.original_generated:
        with st.expander("Original generated version (read-only)"):
            orig_sol = (result.original_generated.get("solution") or {}).get("solution_text")
            st.write(orig_sol or json.dumps(result.original_generated.get("solution"), indent=2)[:2000])

    solution_text = st.text_area(
        "Solution",
        value=result.solution.solution_text if result.solution else "",
        height=260,
    )
    st.markdown("Marking criteria")
    criteria = []
    for i, c in enumerate(result.marking_criteria):
        cols = st.columns([2, 4, 1])
        step = cols[0].text_input("Step", value=c.step_label, key=f"step-{result.question_id}-{i}")
        expected = cols[1].text_input("Expected", value=c.expected_answer, key=f"exp-{result.question_id}-{i}")
        marks = cols[2].number_input("Marks", value=float(c.marks), min_value=0.0, step=0.5, key=f"mk-{result.question_id}-{i}")
        partial = st.text_input("Partial credit", value=c.partial_credit, key=f"pc-{result.question_id}-{i}")
        alt = st.text_input("Alternatives", value=c.alternatives, key=f"alt-{result.question_id}-{i}")
        criteria.append(
            {
                "step_label": step,
                "expected_answer": expected,
                "marks": marks,
                "partial_credit": partial,
                "alternatives": alt,
            }
        )
    current_status = result.syllabus.status.value if result.syllabus else "UNCERTAIN"
    syllabus_status = st.selectbox(
        "Syllabus status",
        [s.value for s in SyllabusStatus],
        index=[s.value for s in SyllabusStatus].index(current_status),
    )
    comment = st.text_area("Faculty comment", value=result.faculty_comment)
    c1, c2, c3 = st.columns(3)
    save = c1.button("Save edits")
    approve = c2.button("Approve question")
    reject = c3.button("Reject question")
    if save or approve or reject:
        try:
            apply_faculty_edit(
                job_id,
                result.question_id,
                solution_text,
                criteria,
                syllabus_status,
                comment,
                approved=approve,
                rejected=reject,
            )
            st.success("Saved.")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

    st.divider()
    st.subheader("Whole-scheme approval")
    ok, reason = can_approve_scheme(scheme)
    st.write(reason)
    if st.button("Approve entire evaluation scheme", disabled=not ok, type="primary"):
        db.update_job(job_id, approval_status=ApprovalStatus.APPROVED.value, status="completed")
        st.success("Scheme marked faculty-approved.")
        st.rerun()
    if st.button("Revert scheme to draft"):
        db.update_job(job_id, approval_status=ApprovalStatus.DRAFT.value)
        st.rerun()

    st.subheader("Export reviewed scheme")
    col = st.columns(3)
    if col[0].button("DOCX"):
        path = export_docx(paper, load_scheme(job_id)["scheme"])
        st.download_button("Download DOCX", path.read_bytes(), path.name, key="dl-docx")
    if col[1].button("PDF"):
        path = export_pdf(paper, load_scheme(job_id)["scheme"])
        st.download_button("Download PDF", path.read_bytes(), path.name, key="dl-pdf")
    if col[2].button("CSV"):
        path = export_csv(load_scheme(job_id)["scheme"])
        st.download_button("Download CSV", path.read_bytes(), path.name, key="dl-csv")

    with st.expander("Future training-dataset export (approved items only)"):
        st.caption("Does not treat unreviewed AI output as training data.")
        if st.button("Show approved dataset JSON"):
            rows = export_training_dataset(load_scheme(job_id)["scheme"], only_approved=True)
            st.json(rows)


def _label(status: ApprovalStatus) -> str:
    if status == ApprovalStatus.APPROVED:
        return "FACULTY-APPROVED"
    return "DRAFT — NOT FACULTY-APPROVED"
