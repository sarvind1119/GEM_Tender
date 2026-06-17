from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from tools.pipeline_runner import APP_DATA_ROOT
from tools.pipeline_runner import create_upload_workspace
from tools.pipeline_runner import make_run_id
from tools.pipeline_runner import read_status
from tools.pipeline_runner import run_pipeline
from tools.pipeline_runner import tender_root_for
from tools.pipeline_runner import write_reviewed_workbook


APP_TITLE = "First-Level Scrutiny System for GeM Bids"


st.set_page_config(
    page_title=APP_TITLE,
    page_icon="G",
    layout="wide",
    initial_sidebar_state="expanded",
)


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
          --ink: #14213d;
          --muted: #52606d;
          --line: #d8dee8;
          --accent: #0f766e;
          --surface: #f7f4ee;
        }
        .stApp {
          background:
            linear-gradient(180deg, rgba(247,244,238,.95), rgba(255,255,255,.98) 34%),
            radial-gradient(circle at 12% 0%, rgba(15,118,110,.12), transparent 28%);
          color: var(--ink);
        }
        [data-testid="stSidebar"] {
          background: #f2efe8;
          border-right: 1px solid var(--line);
        }
        .block-container {
          padding-top: 2.1rem;
          padding-bottom: 3rem;
        }
        .app-kicker {
          color: var(--accent);
          font-size: .78rem;
          font-weight: 800;
          letter-spacing: .12em;
          text-transform: uppercase;
          margin-bottom: .25rem;
        }
        .app-title {
          font-family: Georgia, "Times New Roman", serif;
          font-size: clamp(2rem, 4vw, 4.1rem);
          line-height: .96;
          letter-spacing: -.055em;
          color: var(--ink);
          max-width: 980px;
          margin-bottom: .8rem;
        }
        .app-subtitle {
          max-width: 860px;
          color: var(--muted);
          font-size: 1rem;
          line-height: 1.55;
        }
        .status-strip {
          display: flex;
          gap: .75rem;
          flex-wrap: wrap;
          border-top: 1px solid var(--line);
          border-bottom: 1px solid var(--line);
          padding: .85rem 0;
          margin: 1.2rem 0 1rem;
        }
        .status-pill {
          font-size: .78rem;
          font-weight: 700;
          border: 1px solid var(--line);
          padding: .38rem .65rem;
          border-radius: 999px;
          background: rgba(255,255,255,.72);
        }
        .status-running {
          border-color: rgba(15,118,110,.38);
          color: #0f766e;
          background: rgba(15,118,110,.08);
        }
        .status-failed {
          border-color: rgba(185,28,28,.35);
          color: #991b1b;
          background: rgba(185,28,28,.07);
        }
        .reference-box {
          border-left: 4px solid var(--accent);
          padding: .85rem 1rem;
          background: rgba(255,255,255,.72);
          color: var(--ink);
          min-height: 170px;
          white-space: pre-wrap;
        }
        div[data-testid="stMetric"] {
          background: transparent;
          border-top: 1px solid var(--line);
          padding-top: .75rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def json_load(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def dataframe_from_json(path: Path) -> pd.DataFrame:
    data = json_load(path, [])
    if not data:
        return pd.DataFrame()
    return pd.DataFrame(data)


def user_facing_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df.rename(columns={col: col.replace("preferred_", "") for col in df.columns})


def safe_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    clean = df.fillna("")
    return json.loads(clean.to_json(orient="records", force_ascii=False))


def save_reviewed_dataframe(df: pd.DataFrame, json_path: Path, xlsx_path: Path) -> None:
    rows = safe_records(df)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    write_reviewed_workbook(xlsx_path, rows, list(df.columns))


def download_file(path: Path, label: str, mime: str) -> None:
    if path.exists():
        st.download_button(label, path.read_bytes(), file_name=path.name, mime=mime, use_container_width=True)


def run_folders() -> list[Path]:
    if not APP_DATA_ROOT.exists():
        return []
    return sorted([path for path in APP_DATA_ROOT.iterdir() if path.is_dir()], reverse=True)


def start_background_pipeline(run_id: str, tender_root: Path) -> None:
    thread = threading.Thread(
        target=run_pipeline,
        kwargs={"tender_id": run_id, "tender_root": tender_root, "engine": "auto"},
        daemon=True,
    )
    thread.start()


def collect_uploads(uploaded_files: list[Any] | None) -> list[tuple[str, bytes]]:
    return [(file.name, file.getvalue()) for file in (uploaded_files or [])]


def status_markup(status: dict[str, Any]) -> None:
    if not status:
        st.info("No run selected yet. Upload files and click Process to start.")
        return
    steps = status.get("steps", [])
    completed = sum(1 for step in steps if step.get("status") == "Completed")
    progress = completed / max(len(steps), 1)
    st.progress(progress, text=f"{completed}/{len(steps)} stages completed")
    status_class = "status-running" if status.get("status") == "running" else ""
    if status.get("status") == "failed":
        status_class = "status-failed"
    pills = [f"<span class='status-pill {status_class}'>Run: {status.get('status', 'unknown')}</span>"]
    for step in steps:
        pills.append(f"<span class='status-pill'>{step['label']}: {step['status']}</span>")
    st.markdown("<div class='status-strip'>" + "".join(pills) + "</div>", unsafe_allow_html=True)
    if status.get("error"):
        st.error(status["error"])
    with st.expander("Processing log", expanded=status.get("status") == "running"):
        for item in status.get("logs", [])[-80:]:
            st.write(f"{item.get('ts', '')} - {item.get('message', '')}")


def render_upload_sidebar() -> None:
    st.sidebar.header("Upload")
    tender_files = st.sidebar.file_uploader(
        "Upload Tender Document",
        type=["pdf"],
        accept_multiple_files=True,
        help="Upload the main GeM bid document. ATC PDFs can also be included here.",
    )
    bid_count = int(st.sidebar.number_input("No. of Bids Received", min_value=1, max_value=25, value=3, step=1))
    bidder_names: dict[int, str] = {}
    bidder_uploads: dict[int, list[tuple[str, bytes]]] = {}
    for index in range(1, bid_count + 1):
        st.sidebar.markdown(f"**Bidder {index}**")
        bidder_names[index] = st.sidebar.text_input(f"Bidder {index} name", value="", key=f"bidder_name_{index}")
        files = st.sidebar.file_uploader(
            f"Upload Bidder {index} documents",
            type=["pdf"],
            accept_multiple_files=True,
            key=f"bidder_files_{index}",
        )
        bidder_uploads[index] = collect_uploads(files)

    process = st.sidebar.button("Process", type="primary", use_container_width=True)
    if process:
        tender_uploads = collect_uploads(tender_files)
        if not tender_uploads:
            st.sidebar.error("Upload at least one tender PDF.")
            return
        empty_bidders = [index for index, files in bidder_uploads.items() if not files]
        if empty_bidders:
            st.sidebar.error(f"Upload documents for bidder(s): {', '.join(map(str, empty_bidders))}.")
            return
        run_label = Path(tender_uploads[0][0]).stem
        run_id = make_run_id(run_label)
        tender_root = create_upload_workspace(run_id, tender_uploads, bidder_uploads, bidder_names)
        st.session_state["active_run_id"] = run_id
        start_background_pipeline(run_id, tender_root)
        st.sidebar.success(f"Started run: {run_id}")
        st.rerun()

    folders = run_folders()
    if folders:
        st.sidebar.divider()
        options = [folder.name for folder in folders]
        default_index = 0
        active_run = st.session_state.get("active_run_id")
        if active_run in options:
            default_index = options.index(active_run)
        selected = st.sidebar.selectbox("Open existing run", options, index=default_index)
        st.session_state["active_run_id"] = selected


def render_identity_tab(tender_root: Path) -> None:
    identity_path = tender_root / "05_Extraction_Output" / "02_identity_extraction" / "bidder_identity_summary.json"
    df = dataframe_from_json(identity_path)
    if df.empty:
        st.info("Identity output is not available yet.")
        return
    cols = [
        "bidder_id",
        "bidder_name",
        "pan",
        "pan_status",
        "pan_source_file",
        "pan_page",
        "gstin",
        "gstin_status",
        "gstin_source_file",
        "gstin_page",
        "gstin_pan_match_status",
        "needs_human_review",
    ]
    display_df = user_facing_columns(df)
    st.dataframe(display_df[[col for col in cols if col in display_df.columns]], use_container_width=True, hide_index=True)
    output_dir = tender_root / "05_Extraction_Output" / "02_identity_extraction"
    col1, col2 = st.columns(2)
    with col1:
        download_file(output_dir / "bidder_identity_summary.xlsx", "Download identity summary XLSX", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with col2:
        download_file(output_dir / "pan_gstin_candidates.xlsx", "Download all PAN/GSTIN candidates XLSX", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def render_documents_tab(tender_root: Path) -> None:
    matrix_dir = tender_root / "05_Extraction_Output" / "06_bidder_review_matrix"
    matrix_path = matrix_dir / "bidder_document_review_matrix.json"
    df = dataframe_from_json(matrix_path)
    if df.empty:
        st.info("Required-document matrix is not available yet.")
        return
    st.caption("Document presence is a reviewer aid. `Needs Review` is not a rejection.")
    display_df = user_facing_columns(df)
    edited = st.data_editor(display_df, use_container_width=True, hide_index=True, num_rows="fixed", key="document_matrix_editor")
    if st.button("Save document reviewer edits", use_container_width=True):
        save_reviewed_dataframe(
            edited,
            matrix_dir / "bidder_document_review_matrix_reviewed.json",
            matrix_dir / "bidder_document_review_matrix_reviewed.xlsx",
        )
        st.success("Saved reviewed document matrix.")
    col1, col2 = st.columns(2)
    with col1:
        download_file(matrix_dir / "bidder_document_review_matrix.xlsx", "Download source matrix XLSX", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with col2:
        download_file(matrix_dir / "bidder_document_review_matrix_reviewed.xlsx", "Download reviewed matrix XLSX", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def render_turnover_reference(row: pd.Series, requirement: str) -> None:
    if requirement == "Bidder Turnover":
        source_file = row.get("bidder_turnover_source_file", "")
        source_page = row.get("bidder_turnover_source_page", "")
        evidence = row.get("bidder_turnover_evidence_text", "")
        status = row.get("bidder_turnover_status", "")
    else:
        source_file = row.get("oem_turnover_source_file", "")
        source_page = row.get("oem_turnover_source_page", "")
        evidence = row.get("oem_turnover_evidence_text", "")
        status = row.get("oem_turnover_status", "")
    st.markdown("**Reference Details**")
    st.write(f"Status: `{status}`")
    st.write(f"Document: `{source_file or 'Not found'}`")
    st.write(f"Page: `{source_page or 'Not found'}`")
    st.markdown(f"<div class='reference-box'>{evidence or 'No source text available.'}</div>", unsafe_allow_html=True)


def render_turnover_tab(tender_root: Path) -> None:
    turnover_dir = tender_root / "05_Extraction_Output" / "07_turnover_evaluation"
    matrix_path = turnover_dir / "turnover_review_matrix.json"
    df = dataframe_from_json(matrix_path)
    if df.empty:
        st.info("Turnover review output is not available yet.")
        return
    table_col, ref_col = st.columns([1.55, 1])
    with table_col:
        st.caption("All turnover suggestions require human review.")
        edited = st.data_editor(df, use_container_width=True, hide_index=True, num_rows="fixed", key="turnover_matrix_editor")
        if st.button("Save turnover reviewer edits", use_container_width=True):
            save_reviewed_dataframe(
                edited,
                turnover_dir / "turnover_review_matrix_reviewed.json",
                turnover_dir / "turnover_review_matrix_reviewed.xlsx",
            )
            st.success("Saved reviewed turnover matrix.")
        col1, col2 = st.columns(2)
        with col1:
            download_file(turnover_dir / "turnover_review_matrix.xlsx", "Download turnover XLSX", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        with col2:
            download_file(turnover_dir / "turnover_llm_results.xlsx", "Download LLM details XLSX", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with ref_col:
        bidder_labels = [f"{row.bidder_id} - {row.bidder_name}" for row in df.itertuples()]
        selected_bidder = st.selectbox("Bidder reference", bidder_labels)
        requirement = st.radio("Requirement", ["Bidder Turnover", "OEM Turnover"], horizontal=True)
        row_index = bidder_labels.index(selected_bidder)
        render_turnover_reference(df.iloc[row_index], requirement)


def render_downloads_tab(tender_root: Path) -> None:
    output_root = tender_root / "05_Extraction_Output"
    downloads = [
        ("Document manifest", output_root / "document_manifest.xlsx"),
        ("All document text index", output_root / "01_text_extraction" / "all_document_text_index.xlsx"),
        ("Required document attributes", output_root / "05_tender_requirements" / "required_document_attributes.xlsx"),
        ("Bidder document review matrix", output_root / "06_bidder_review_matrix" / "bidder_document_review_matrix.xlsx"),
        ("Turnover review matrix", output_root / "07_turnover_evaluation" / "turnover_review_matrix.xlsx"),
    ]
    for label, path in downloads:
        download_file(path, f"Download {label}", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def render_main() -> None:
    inject_css()
    st.markdown("<div class='app-kicker'>Local pilot workspace</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='app-title'>{APP_TITLE}</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='app-subtitle'>Upload a GeM tender and bidder submissions, run the current OCR and review agents, then inspect source-backed findings before any human decision.</div>",
        unsafe_allow_html=True,
    )

    render_upload_sidebar()
    run_id = st.session_state.get("active_run_id")
    if not run_id:
        status_markup({})
        return
    tender_root = tender_root_for(run_id)
    status = read_status(tender_root)
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Selected run", run_id)
    with col2:
        st.metric("Pipeline status", status.get("status", "not started") if status else "not started")
    with col3:
        st.metric("Workspace", str(tender_root))
    status_markup(status)

    tabs = st.tabs(["Agent 1: Identity", "Agent 2: Required Documents", "Agent 3: Turnover", "Downloads"])
    with tabs[0]:
        render_identity_tab(tender_root)
    with tabs[1]:
        render_documents_tab(tender_root)
    with tabs[2]:
        render_turnover_tab(tender_root)
    with tabs[3]:
        render_downloads_tab(tender_root)

    if status.get("status") == "running":
        time.sleep(2)
        st.rerun()


if __name__ == "__main__":
    render_main()
