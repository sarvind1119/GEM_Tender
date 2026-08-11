from __future__ import annotations

from pathlib import Path

import streamlit as st

from tools.pipeline_runner import tender_root_for
from ui.common import APP_TITLE, friendly_run_name, inject_styles, render_workspace_header, run_folders
from ui.pages import export, requirements, review, setup


PAGES = ("Tender Setup", "Tender Requirements", "Review Bidders", "Export & Audit")


def _selected_root() -> Path | None:
    run_id = st.session_state.get("active_run_id")
    if not run_id:
        return None
    root = tender_root_for(str(run_id))
    return root if root.exists() else None


def run() -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="G",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_styles()

    st.sidebar.markdown("<div class='gem-brand'>GeM Bid Scrutiny</div>", unsafe_allow_html=True)
    folders = run_folders()
    creating_new = bool(st.session_state.get("creating_new_tender"))
    if folders and not creating_new:
        options = [path.name for path in folders]
        current = st.session_state.get("active_run_id")
        index = options.index(current) if current in options else 0
        selected = st.sidebar.selectbox(
            "Tender workspace",
            options,
            index=index,
            format_func=lambda value: friendly_run_name(tender_root_for(value)),
        )
        if selected != current:
            st.session_state["active_run_id"] = selected
    elif creating_new and folders:
        st.sidebar.info("Creating a new tender workspace.")
        if st.sidebar.button("Return to existing tenders", width="stretch"):
            st.session_state["creating_new_tender"] = False
            st.rerun()

    page = st.sidebar.radio("Workflow", PAGES)
    st.sidebar.divider()
    if st.sidebar.button("Create another tender", width="stretch"):
        st.session_state.pop("active_run_id", None)
        st.session_state["creating_new_tender"] = True
        st.session_state["workflow_override"] = "Tender Setup"
        st.rerun()
    st.sidebar.caption("Local pilot · Human decision authority retained")

    if st.session_state.pop("workflow_override", None):
        page = "Tender Setup"
    tender_root = _selected_root()
    render_workspace_header(tender_root)

    if page == "Tender Setup":
        setup.render(tender_root)
    elif page == "Tender Requirements":
        requirements.render(tender_root)
    elif page == "Review Bidders":
        review.render(tender_root)
    else:
        export.render(tender_root)
