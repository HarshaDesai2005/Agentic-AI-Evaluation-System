from __future__ import annotations

import streamlit as st

from database import db
from services.export_service import export_csv, export_docx, export_pdf
from services.workflow_orchestrator import load_scheme, run_job
from ui.styles import badge, hero, inject


def _status_kind(status: str) -> str:
    mapping = {
        "IN": "in",
        "OUT": "out",
        "PARTIAL": "partial",
        "UNCERTAIN": "uncertain",
    }
    return mapping.get(status, "info")


def render() -> None:
    inject()
    hero("Evaluation results", "Question-wise solutions, marking schemes, evidence and validation.")
    jobs = db.list_jobs(30)
    if not jobs:
        st.info("No jobs yet.")
        return
    labels = {f"{j['subject_code']} · {j['subject_name']} · {j['id']}": j["id"] for j in jobs}
    default = st.session_state.get("active_job_id")
    options = list(labels.keys())
    index = 0
    if default:
        for i, (label, jid) in enumerate(labels.items()):
            if jid == default:
                index = i
                break
    selected = st.selectbox("Evaluation job", options, index=index)
    job_id = labels[selected]
    st.session_state["active_job_id"] = job_id
    payload = load_scheme(job_id)
    if not payload:
        st.error("Could not load this job.")
        return
    paper = payload["paper"]
    scheme = payload["scheme"]
    job = payload["job"]

    st.markdown(
        badge(job["status"], "info")
        + badge(scheme.approval_status.value, "ok" if scheme.approval_status.value == "faculty_approved" else "warn")
        + badge(
            "All questions covered" if scheme.all_questions_covered else "Coverage gap",
            "ok" if scheme.all_questions_covered else "err",
        ),
        unsafe_allow_html=True,
    )
    st.caption(
        f"Printed total: {scheme.paper_total_marks} · Attempt total: {scheme.attempt_total_marks} · "
        f"Allocated sum: {scheme.scheme_total_marks}"
    )
    if scheme.issues:
        with st.expander("Validation issues", expanded=True):
            for issue in scheme.issues:
                st.write(f"[{issue.severity}] {issue.message}")

    if not scheme.questions:
        st.warning("No generated results yet. Run the workflow from New Evaluation.")
        return

    ids = [q.display_number for q in scheme.questions]
    current = st.selectbox("Question", ids)
    result = next(q for q in scheme.questions if q.display_number == current)

    st.markdown(f'<div class="card"><div class="q-head">Question {result.display_number}</div>', unsafe_allow_html=True)
    st.write(result.question_text)
    st.write(f"Marks: **{result.marks}**")
    if result.analysis:
        st.caption(
            f"Type: {result.analysis.question_type.value} · Topic: {result.analysis.topic or '—'} · "
            f"{result.analysis.expected_format}"
        )
    if result.syllabus:
        st.markdown(
            badge(result.syllabus.status.value, _status_kind(result.syllabus.status.value))
            + f" {result.syllabus.unit or ''} {result.syllabus.topic or ''}",
            unsafe_allow_html=True,
        )
        st.write(result.syllabus.reason)
        for ev in result.syllabus.evidence[:4]:
            page = f" p.{ev.page_number}" if ev.page_number else ""
            verified = "verified" if ev.verified else "unverified"
            st.caption(f"Syllabus source: {ev.filename}{page} ({verified})")
            st.text(ev.quote[:400])
    st.markdown("**Solution**")
    st.write(result.solution.solution_text if result.solution else "(missing)")
    if result.solution and result.solution.key_points:
        st.markdown("**Key points**")
        for kp in result.solution.key_points:
            st.markdown(f"- {kp}")
    st.markdown("**Marking scheme**")
    if result.marking_criteria:
        st.table(
            [
                {
                    "Component": c.step_label,
                    "Expected": c.expected_answer,
                    "Marks": c.marks,
                    "Partial credit": c.partial_credit,
                    "Alternatives": c.alternatives,
                }
                for c in result.marking_criteria
            ]
        )
        kind = "ok" if result.marks_match else "err"
        st.markdown(
            badge(
                f"Allocated {result.allocated_marks_sum} / {result.marks}",
                kind,
            ),
            unsafe_allow_html=True,
        )
    if result.solution:
        st.markdown("**Supporting sources**")
        for ev in result.solution.evidence:
            page = f" p.{ev.page_number}" if ev.page_number else ""
            st.caption(f"{ev.filename}{page} score={ev.score}")
            st.text(ev.quote[:350])
        if result.solution.used_model_knowledge:
            st.warning("This answer includes model general knowledge, not only retrieved documents.")
        if result.solution.insufficient_evidence:
            st.error("Insufficient evidence warning.")
    if result.validation_issues:
        st.markdown("**Warnings**")
        for w in result.validation_issues:
            st.write(f"- {w}")
    st.caption(f"Status: {result.status} · approved={result.approved} · reviewed={result.reviewed}")
    st.markdown("</div>", unsafe_allow_html=True)

    if st.button("Retry this question"):
        try:
            run_job(job_id, paper, only_question_id=result.question_id, progress=lambda m: st.write(m))
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

    st.subheader("Export")
    c1, c2, c3 = st.columns(3)
    if c1.button("Generate DOCX"):
        path = export_docx(paper, scheme)
        st.download_button("Download DOCX", data=path.read_bytes(), file_name=path.name, mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    if c2.button("Generate PDF"):
        path = export_pdf(paper, scheme)
        st.download_button("Download PDF", data=path.read_bytes(), file_name=path.name, mime="application/pdf")
    if c3.button("Generate CSV"):
        path = export_csv(scheme)
        st.download_button("Download CSV", data=path.read_bytes(), file_name=path.name, mime="text/csv")
