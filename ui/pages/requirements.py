from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st


def _load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def render(tender_root: Path | None) -> None:
    st.subheader("Tender requirements")
    st.caption("Confirm what the tender asks bidders to submit or satisfy before reviewing bidder evidence.")
    if tender_root is None:
        st.info("Open or create a tender workspace first.")
        return
    path = tender_root / "05_Extraction_Output" / "05_tender_requirements" / "required_document_attributes.json"
    rows = _load(path)
    if not rows:
        st.info("Tender requirements are not available yet.")
        return

    assessed = [row for row in rows if str(row.get("presence_check_ready", "")).casefold() == "yes"]
    manual = [row for row in rows if row not in assessed]
    col1, col2, col3 = st.columns(3)
    col1.metric("Requirements", len(rows))
    col2.metric("System-assessable", len(assessed))
    col3.metric("Manual review", len(manual))

    view = st.radio(
        "Requirement group",
        ["All", "System-assessable", "Manual review"],
        horizontal=True,
        label_visibility="collapsed",
    )
    visible = rows if view == "All" else assessed if view == "System-assessable" else manual
    for row in visible:
        requirement_id = str(row.get("requirement_id", ""))
        text = str(row.get("normalized_item_text") or row.get("requirement_text") or "Requirement")
        source_file = str(row.get("source_file") or "")
        source_page = row.get("source_page") or ""
        with st.expander(f"{requirement_id} · {text[:110]}"):
            st.write(text)
            expected = str(row.get("expected_bidder_evidence") or "")
            if expected:
                st.caption(f"Expected evidence: {expected}")
            st.caption(f"Tender source: {source_file or 'Unavailable'} · page {source_page or '—'}")
            snippet = str(row.get("source_snippet") or row.get("source_text_snippet") or "")
            if snippet:
                st.text_area(
                    "Tender source text",
                    snippet,
                    disabled=True,
                    height=100,
                    key=f"req_source_{requirement_id}",
                )
            if str(row.get("needs_clause_expansion", "")).casefold() == "yes":
                st.warning("This condition is not currently assessable by the system and remains routed to manual review.")

