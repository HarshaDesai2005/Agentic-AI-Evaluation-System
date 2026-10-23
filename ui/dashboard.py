from __future__ import annotations

import streamlit as st

import config
from database import db
from services.ollama_service import get_ollama
from services.retrieval_service import get_knowledge_base
from ui.styles import badge, hero, inject


def render() -> None:
    inject()
    hero(
        config.APP_NAME,
        "Generate evaluation schemes and solutions locally from a question paper, "
        "official syllabus, textbooks and notes. Documents never leave this computer for LLM inference.",
    )
    st.markdown(
        '<div class="confidential">Confidential examination material. Bind is localhost by default. '
        "Do not treat this student project as institutionally certified security.</div>",
        unsafe_allow_html=True,
    )

    ollama = get_ollama().health()
    try:
        kb_stats = get_knowledge_base().stats()
        kb_ok = True
        kb_msg = f"{kb_stats['chunk_count']} chunks · {kb_stats['documents']} docs · {kb_stats['backend']}"
    except Exception as exc:  # noqa: BLE001
        kb_ok = False
        kb_msg = f"Knowledge base unavailable ({type(exc).__name__})"

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Local model")
        if ollama["model_present"]:
            st.markdown(badge("READY", "ok") + f" `{config.OLLAMA_MODEL}`", unsafe_allow_html=True)
        elif ollama["reachable"]:
            st.markdown(badge("MODEL MISSING", "warn"), unsafe_allow_html=True)
        else:
            st.markdown(badge("OLLAMA OFFLINE", "err"), unsafe_allow_html=True)
        st.caption(ollama["message"].split("\n")[0])
        st.markdown("</div>", unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Knowledge base")
        st.markdown(badge("READY" if kb_ok else "ERROR", "ok" if kb_ok else "err"), unsafe_allow_html=True)
        st.caption(kb_msg)
        st.markdown("</div>", unsafe_allow_html=True)
    with c3:
        jobs = db.list_jobs(8)
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("Recent jobs")
        st.markdown(badge(str(len(jobs)), "info") + " shown", unsafe_allow_html=True)
        st.caption("Open Evaluation Results after a run.")
        st.markdown("</div>", unsafe_allow_html=True)

    if not ollama["model_present"]:
        with st.expander("Ollama setup instructions", expanded=True):
            st.code(ollama["message"])

    st.subheader("Recent evaluation jobs")
    jobs = db.list_jobs(15)
    if not jobs:
        st.info("No evaluations yet. Start one from **New Evaluation**.")
        return
    for job in jobs:
        cols = st.columns([2, 1, 1, 1.4])
        cols[0].markdown(f"**{job['subject_name']}** `{job['subject_code']}`")
        cols[1].write(job["status"])
        cols[2].write(job.get("approval_status") or "unreviewed")
        if cols[3].button("Open", key=f"open-{job['id']}"):
            st.session_state["active_job_id"] = job["id"]
            st.session_state["nav"] = "Evaluation Results"
            st.rerun()
        if job.get("error"):
            st.caption(job["error"][:240])
