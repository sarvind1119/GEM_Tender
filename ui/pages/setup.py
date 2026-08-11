from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from tools.pipeline_runner import (
    append_bidder_uploads,
    create_tender_preview_workspace,
    make_run_id,
    read_status,
    run_tender_requirement_preview,
)
from ui.common import has_bidder_documents, start_background_pipeline, status_summary


def _uploads(files: list[Any] | None) -> list[tuple[str, bytes]]:
    return [(file.name, file.getvalue()) for file in (files or [])]


def render(tender_root: Path | None) -> None:
    st.subheader("Tender setup")
    st.caption("Upload the tender first, confirm that requirements were extracted, then attach bidder submissions.")

    if tender_root is None:
        tender_files = st.file_uploader(
            "Tender and ATC documents",
            type=["pdf"],
            accept_multiple_files=True,
            help="Upload the main GeM bid document and any available ATC PDFs.",
        )
        if st.button("Analyze tender requirements", type="primary"):
            uploads = _uploads(tender_files)
            if not uploads:
                st.error("Upload at least one tender PDF.")
                return
            run_id = make_run_id(Path(uploads[0][0]).stem)
            root = create_tender_preview_workspace(run_id, uploads)
            st.session_state["active_run_id"] = run_id
            st.session_state["creating_new_tender"] = False
            with st.spinner("Reading the tender and extracting requirements…"):
                result = run_tender_requirement_preview(run_id, root, engine="auto")
            if result.get("status") == "failed":
                st.error(result.get("error", "Tender analysis failed."))
            else:
                st.success("Tender requirements are ready for review.")
                st.rerun()
        return

    status = read_status(tender_root)
    status_summary(status)
    tender_files = sorted((tender_root / "01_Tender_Documents").glob("*.pdf"))
    if tender_files:
        st.markdown("**Tender documents**")
        for path in tender_files:
            st.write(f"• {path.name}")

    ready = status.get("status") in {"requirements_ready", "completed", "failed"} or has_bidder_documents(tender_root)
    if not ready:
        st.info("Bidder upload becomes available after tender requirement extraction completes.")
        return

    st.divider()
    st.subheader("Bidder submissions")
    st.caption("The normal workload is up to 10 bidders; the technical limit remains 25.")
    bid_count = int(st.number_input("Number of bidders", min_value=1, max_value=25, value=3, step=1))
    if bid_count > 10:
        st.warning("This pilot is optimized for up to 10 bidders. Larger runs may require more navigation.")

    names: dict[int, str] = {}
    uploads_by_bidder: dict[int, list[tuple[str, bytes]]] = {}
    for index in range(1, bid_count + 1):
        with st.expander(f"Bidder {index:02d}", expanded=index == 1):
            names[index] = st.text_input(
                "Bidder label",
                key=f"setup_bidder_name_{index}",
                help="Use the name officials recognize. Extraction will preserve its own raw name separately.",
            )
            files = st.file_uploader(
                "PDF submissions",
                type=["pdf"],
                accept_multiple_files=True,
                key=f"setup_bidder_files_{index}",
            )
            uploads_by_bidder[index] = _uploads(files)
            if files:
                st.caption(f"{len(files)} file(s): " + ", ".join(file.name for file in files))

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Process bidder submissions", type="primary", width="stretch"):
            empty = [index for index, files in uploads_by_bidder.items() if not files]
            if empty:
                st.error(f"Upload documents for bidder(s): {', '.join(map(str, empty))}.")
            else:
                append_bidder_uploads(tender_root, uploads_by_bidder, names)
                start_background_pipeline(tender_root.name, tender_root)
                st.success("Bidder processing started.")
                st.rerun()
    with col2:
        if has_bidder_documents(tender_root) and st.button(
            "Rerun existing bidder processing",
            width="stretch",
            disabled=status.get("status") == "running",
        ):
            start_background_pipeline(tender_root.name, tender_root)
            st.success("Bidder processing restarted.")
            st.rerun()
