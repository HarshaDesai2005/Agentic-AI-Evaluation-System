"""Local Streamlit entry point. Bound to localhost by default."""

from __future__ import annotations

import streamlit as st

import config
from database import db
from services.security_service import passwords_match
from ui import dashboard, evaluation_results, faculty_review, knowledge_base, new_evaluation
from ui.styles import inject

st.set_page_config(
    page_title=config.APP_SHORT_NAME,
    page_icon="📘",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject()
db.init_db()

PAGES = {
    "Dashboard": dashboard.render,
    "New Evaluation": new_evaluation.render,
    "Knowledge Base": knowledge_base.render,
    "Evaluation Results": evaluation_results.render,
    "Faculty Review": faculty_review.render,
}


def _login() -> bool:
    if not config.AUTH_ENABLED:
        return True
    if st.session_state.get("authed"):
        return True
    st.markdown("### Sign in")
    st.caption("Basic local authentication. Enable only when more than one person uses this machine.")
    user = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Sign in"):
        if user == config.APP_USERNAME and config.APP_PASSWORD and passwords_match(password, config.APP_PASSWORD):
            st.session_state["authed"] = True
            st.rerun()
        st.error("Invalid credentials.")
    return False


def main() -> None:
    if not _login():
        return
    with st.sidebar:
        st.markdown(f"### {config.APP_SHORT_NAME}")
        st.caption("Local RAG · Ollama · faculty review")
        choice = st.radio(
            "Navigate",
            list(PAGES.keys()),
            index=list(PAGES.keys()).index(st.session_state.get("nav", "Dashboard"))
            if st.session_state.get("nav") in PAGES
            else 0,
        )
        st.session_state["nav"] = choice
        st.divider()
        st.caption(f"Model: `{config.OLLAMA_MODEL}`")
        st.caption("Address: 127.0.0.1 (default)")
        st.caption("No cloud LLM fallback.")
        if config.AUTH_ENABLED and st.button("Sign out"):
            st.session_state["authed"] = False
            st.rerun()
    PAGES[st.session_state["nav"]]()


if __name__ == "__main__":
    main()
else:
    main()
