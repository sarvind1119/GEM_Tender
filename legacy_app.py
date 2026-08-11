from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from tools.pipeline_runner import APP_DATA_ROOT
from tools.pipeline_runner import append_bidder_uploads
from tools.pipeline_runner import create_tender_preview_workspace
from tools.pipeline_runner import make_run_id
from tools.pipeline_runner import mark_run_failed
from tools.pipeline_runner import read_status
from tools.pipeline_runner import run_pipeline
from tools.pipeline_runner import run_tender_requirement_preview
from tools.pipeline_runner import tender_root_for
from tools.pipeline_runner import write_reviewed_workbook


APP_TITLE = "First-Level Scrutiny System for GeM Bids"

# A run whose status file has not been touched for this long while still "running"
# is treated as possibly stalled (e.g. the app restarted and the worker thread is gone).
STALE_AFTER_SECONDS = 300
STALE_QUEUED_AFTER_SECONDS = 30
PREVIEW_STEP_LABELS = {
    "agent_1_identity": "Reading tender text",
    "agent_2_required_documents": "Extracting bidder requirements",
}


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
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # An output still being written, or a partial file from a killed worker,
        # should degrade to "not available yet" rather than crash the page.
        return default


def seconds_since(iso_ts: str) -> float | None:
    if not iso_ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(iso_ts, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (datetime.now(parsed.tzinfo) - parsed).total_seconds()
    return None


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
    # Write the lock-prone workbook first; if it fails (e.g. open in Excel) the JSON
    # is left untouched so the two outputs stay in sync.
    write_reviewed_workbook(xlsx_path, rows, list(df.columns))
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


def try_save_reviewed(df: pd.DataFrame, json_path: Path, xlsx_path: Path, success_msg: str) -> None:
    try:
        save_reviewed_dataframe(df, json_path, xlsx_path)
    except PermissionError as exc:
        st.error(str(exc))
    except Exception as exc:  # noqa: BLE001 - surface any save failure instead of crashing
        st.error(f"Could not save reviewer edits: {exc}")
    else:
        st.success(success_msg)


def download_file(path: Path, label: str, mime: str) -> None:
    if path.exists():
        st.download_button(label, path.read_bytes(), file_name=path.name, mime=mime, use_container_width=True)


def run_folders() -> list[Path]:
    if not APP_DATA_ROOT.exists():
        return []
    return sorted([path for path in APP_DATA_ROOT.iterdir() if path.is_dir()], reverse=True)


def has_bidder_documents(tender_root: Path) -> bool:
    bidder_root = tender_root / "03_Bidder_Submissions"
    return bidder_root.exists() and any(bidder_root.rglob("*.pdf"))


def stale_queued(status: dict[str, Any]) -> bool:
    if status.get("status") != "queued":
        return False
    idle = seconds_since(status.get("updated_at", "") or status.get("started_at", ""))
    return idle is None or idle > STALE_QUEUED_AFTER_SECONDS


def maybe_auto_refresh(status: dict[str, Any], tender_root: Path) -> None:
    if status.get("status") != "running":
        return
    idle = seconds_since(status.get("updated_at", ""))
    if idle is not None and idle > STALE_AFTER_SECONDS:
        st.warning(
            f"No pipeline progress for ~{int(idle)}s. A long OCR job can cause this, "
            "but if the app was restarted the background worker may be gone."
        )
        if st.button("Reset this run to failed", key="reset_stalled_run"):
            mark_run_failed(tender_root, "Run reset to failed after a stall (no status heartbeat).")
            st.rerun()
    time.sleep(2)
    st.rerun()


def start_background_pipeline(run_id: str, tender_root: Path) -> None:
    thread = threading.Thread(
        target=run_pipeline,
        kwargs={"tender_id": run_id, "tender_root": tender_root, "engine": "auto"},
        daemon=True,
    )
    thread.start()


def collect_uploads(uploaded_files: list[Any] | None) -> list[tuple[str, bytes]]:
    return [(file.name, file.getvalue()) for file in (uploaded_files or [])]


def status_markup(status: dict[str, Any], tender_root: Path | None = None) -> None:
    if not status:
        st.info("No run selected yet. Upload a tender and click Analyze Tender Requirements to start.")
        return
    steps = status.get("steps", [])
    preview_only = tender_root is not None and not has_bidder_documents(tender_root)
    if preview_only:
        steps = [step for step in steps if step.get("step_id") in PREVIEW_STEP_LABELS]
        for step in steps:
            step["label"] = PREVIEW_STEP_LABELS.get(step.get("step_id", ""), step.get("label", ""))
    completed = sum(1 for step in steps if step.get("status") == "Completed")
    progress = completed / max(len(steps), 1)
    stage_label = "tender stages" if preview_only else "stages"
    st.progress(progress, text=f"{completed}/{len(steps)} {stage_label} completed")
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
    st.sidebar.subheader("Step 1: Tender")
    tender_files = st.sidebar.file_uploader(
        "Upload Tender Document",
        type=["pdf"],
        accept_multiple_files=True,
        help="Upload the main GeM bid document. ATC PDFs can also be included here.",
    )

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

    active_run_id = st.session_state.get("active_run_id")
    status = read_status(tender_root_for(active_run_id)) if active_run_id else {}
    tender_root = tender_root_for(active_run_id) if active_run_id else None
    run_in_progress = status.get("status") == "running"
    selected_stale_queued = stale_queued(status)
    analyze = st.sidebar.button(
        "Analyze Tender Requirements",
        type="primary",
        use_container_width=True,
        disabled=run_in_progress,
    )
    if run_in_progress:
        st.sidebar.caption("A run is in progress. Wait for it to finish before starting another.")
    if analyze:
        tender_uploads = collect_uploads(tender_files)
        if not tender_uploads:
            st.sidebar.error("Upload at least one tender PDF.")
            return
        run_label = Path(tender_uploads[0][0]).stem
        run_id = make_run_id(run_label)
        tender_root = create_tender_preview_workspace(run_id, tender_uploads)
        st.session_state["active_run_id"] = run_id
        with st.spinner("Reading tender and extracting bidder requirements..."):
            result = run_tender_requirement_preview(run_id, tender_root, engine="auto")
        if result.get("status") == "failed":
            st.sidebar.error(result.get("error", "Tender analysis failed."))
        else:
            st.sidebar.success("Tender requirements extracted.")
        st.rerun()

    if active_run_id and tender_root is not None and selected_stale_queued:
        st.sidebar.warning("This selected run is still queued. Restart tender analysis to recover it.")
        if st.sidebar.button("Restart Tender Analysis", use_container_width=True):
            with st.spinner("Restarting tender analysis..."):
                result = run_tender_requirement_preview(active_run_id, tender_root, engine="auto")
            if result.get("status") == "failed":
                st.sidebar.error(result.get("error", "Tender analysis failed."))
            else:
                st.sidebar.success("Tender requirements extracted.")
            st.rerun()

    can_upload_bidders = bool(active_run_id) and (
        status.get("status") in {"requirements_ready", "completed"} or (tender_root is not None and has_bidder_documents(tender_root))
    )
    if can_upload_bidders:
        st.sidebar.divider()
        st.sidebar.subheader("Step 2: Bidders")
        existing_bidder_docs = tender_root is not None and has_bidder_documents(tender_root)
        if existing_bidder_docs and status.get("status") in {"failed", "completed"}:
            if st.sidebar.button("Rerun Bidder Processing", use_container_width=True, disabled=run_in_progress):
                start_background_pipeline(active_run_id, tender_root)
                st.sidebar.success(f"Restarted bidder processing: {active_run_id}")
                st.rerun()
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
        process_bidders = st.sidebar.button(
            "Process Bidders",
            type="primary",
            use_container_width=True,
            disabled=run_in_progress,
        )
        if process_bidders:
            empty_bidders = [index for index, files in bidder_uploads.items() if not files]
            if empty_bidders:
                st.sidebar.error(f"Upload documents for bidder(s): {', '.join(map(str, empty_bidders))}.")
                return
            tender_root = tender_root_for(active_run_id)
            append_bidder_uploads(tender_root, bidder_uploads, bidder_names)
            start_background_pipeline(active_run_id, tender_root)
            st.sidebar.success(f"Started bidder processing: {active_run_id}")
            st.rerun()


def render_bidder_requirements_preview(tender_root: Path) -> None:
    req_dir = tender_root / "05_Extraction_Output" / "05_tender_requirements"
    req_path = req_dir / "bidder_requirements.json"
    df = dataframe_from_json(req_path)
    if df.empty:
        st.info("Bidder requirements preview is not available yet.")
        return

    st.markdown("**Requirements Found In Tender**")
    st.caption("OCR has read the tender and extracted the requirements bidders may need to satisfy or submit.")

    def column_or_blank(column: str) -> pd.Series:
        if column in df.columns:
            return df[column].fillna("").astype(str)
        return pd.Series([""] * len(df))

    display_df = pd.DataFrame()
    display_df["Type"] = column_or_blank("requirement_type").str.replace("_", " ").str.title()
    display_df["Requirement Asked In Tender"] = column_or_blank("requirement_text")
    display_df["Expected Bidder Evidence"] = column_or_blank("expected_bidder_evidence")
    source_file = column_or_blank("source_file")
    source_page = column_or_blank("source_page")
    display_df["Source"] = [
        f"{file} p.{page}" if page else file
        for file, page in zip(source_file, source_page)
    ]
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    with st.expander("Show source snippets"):
        for row in safe_records(df):
            st.markdown(f"**{row.get('requirement_id', '')}: {row.get('requirement_text', '')}**")
            st.write(f"Source: `{row.get('source_file', '')}` page `{row.get('source_page', '')}`")
            st.markdown(f"<div class='reference-box'>{row.get('source_snippet', '') or 'No source text available.'}</div>", unsafe_allow_html=True)

    download_file(req_dir / "bidder_requirements.xlsx", "Download bidder requirements XLSX", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


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

    # --- registry verification (tools/verification) ---
    render_registry_verification(tender_root, df)
    # --- end registry verification ---


def render_registry_verification(tender_root: Path, identity_df: pd.DataFrame) -> None:
    import os

    from tools.verification import cin_extraction as verification_cins
    from tools.verification import engine as verification_engine
    from tools.verification.schema import ALL_SERVICES

    st.divider()
    st.subheader("Registry verification (PAN / GSTN / MCA)")
    provider_modes = ", ".join(
        f"{service.upper()}: {os.environ.get(f'VERIFY_{service.upper()}_PROVIDER', 'mock')}"
        for service in ALL_SERVICES
    )
    st.caption(
        f"Provider mode - {provider_modes}. Registry results are reviewer evidence only; "
        "they never decide eligibility. External (non-local) calls stay disabled unless "
        "VERIFY_ENABLED=true in tools/.env."
    )

    bidder_ids = [str(value) for value in identity_df.get("bidder_id", pd.Series(dtype=str)).tolist()]
    selected_bidders = st.multiselect("Bidders to verify", bidder_ids, default=bidder_ids)
    service_cols = st.columns(len(ALL_SERVICES))
    selected_services = [
        service
        for service, column in zip(ALL_SERVICES, service_cols)
        if column.checkbox(service.upper(), value=True, key=f"verify_service_{service}")
    ]

    extracted_cins = verification_cins.cin_candidates_by_bidder(tender_root)
    cin_map: dict[str, str] = {}
    if "mca" in selected_services and selected_bidders:
        with st.expander("CIN / LLPIN inputs for the MCA check", expanded=False):
            st.caption(
                "Pre-filled when bidder documents contain exactly one CIN. "
                "Manual entry overrides document extraction."
            )
            for bidder_id in selected_bidders:
                candidates = extracted_cins.get(bidder_id, [])
                prefill = verification_cins.unique_cin_for_bidder(candidates)
                if candidates and not prefill:
                    distinct = sorted({row["cin"] for row in candidates})
                    st.warning(f"{bidder_id}: multiple CIN candidates found: {', '.join(distinct)}")
                value = st.text_input(
                    f"{bidder_id} CIN",
                    value=prefill,
                    key=f"verify_cin_{bidder_id}",
                    help="Company CIN (e.g. U12345MH2010PTC123456). Leave blank to skip the MCA check.",
                )
                if value.strip():
                    cin_map[bidder_id] = value.strip().upper()

    if st.button("Run registry verification", type="primary", use_container_width=True):
        if not selected_bidders or not selected_services:
            st.error("Select at least one bidder and one service.")
        else:
            with st.spinner("Contacting registries..."):
                try:
                    summary = verification_engine.run_verification(
                        tender_root,
                        bidder_ids=selected_bidders,
                        services=tuple(selected_services),
                        cin_map=cin_map,
                        triggered_by="ui_button",
                        log=lambda message: None,
                    )
                except Exception as exc:  # noqa: BLE001 - surface, never crash the tab
                    st.error(f"Verification could not be completed: {exc}")
                else:
                    st.success(
                        f"Done: {summary.get('verified', 0)} verified, "
                        f"{summary.get('flagged', 0)} flagged, {summary.get('not_found', 0)} not found, "
                        f"{summary.get('errors', 0)} errors, {summary.get('skipped', 0)} skipped."
                    )
                    st.rerun()

    matrix_df = dataframe_from_json(verification_engine.matrix_json_path(tender_root))
    if matrix_df.empty:
        st.info("No registry verification results yet for this run.")
        return
    display_cols = [
        "bidder_id",
        "bidder_name",
        "service",
        "input_value",
        "outcome",
        "registry_status",
        "registered_name",
        "name_match_band",
        "review_note",
        "provider",
        "verified_at",
    ]
    st.dataframe(
        matrix_df[[col for col in display_cols if col in matrix_df.columns]],
        use_container_width=True,
        hide_index=True,
    )
    download_file(
        verification_engine.matrix_xlsx_path(tender_root),
        "Download registry verification XLSX",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def render_documents_tab(tender_root: Path) -> None:
    matrix_dir = tender_root / "05_Extraction_Output" / "06_bidder_review_matrix"
    matrix_path = matrix_dir / "bidder_document_review_matrix.json"
    df = dataframe_from_json(matrix_path)
    if df.empty:
        st.info("Bidder requirements matrix is not available yet.")
        return
    st.caption("Bidder requirement checks are reviewer aids. `Needs Review` is not a rejection.")
    display_df = user_facing_columns(df)
    edited = st.data_editor(display_df, use_container_width=True, hide_index=True, num_rows="fixed", key="document_matrix_editor")
    if st.button("Save document reviewer edits", use_container_width=True):
        try_save_reviewed(
            edited,
            matrix_dir / "bidder_document_review_matrix_reviewed.json",
            matrix_dir / "bidder_document_review_matrix_reviewed.xlsx",
            "Saved reviewed bidder requirements matrix.",
        )
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
            try_save_reviewed(
                edited,
                turnover_dir / "turnover_review_matrix_reviewed.json",
                turnover_dir / "turnover_review_matrix_reviewed.xlsx",
                "Saved reviewed turnover matrix.",
            )
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
        ("Bidder requirements preview", output_root / "05_tender_requirements" / "bidder_requirements.xlsx"),
        ("Bidder requirement attributes", output_root / "05_tender_requirements" / "required_document_attributes.xlsx"),
        ("Bidder requirements matrix", output_root / "06_bidder_review_matrix" / "bidder_document_review_matrix.xlsx"),
        ("Turnover review matrix", output_root / "07_turnover_evaluation" / "turnover_review_matrix.xlsx"),
    ]
    for label, path in downloads:
        download_file(path, f"Download {label}", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def render_main() -> None:
    inject_css()
    st.markdown("<div class='app-kicker'>Local pilot workspace</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='app-title'>{APP_TITLE}</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='app-subtitle'>Upload a GeM tender, preview bidder requirements from the tender, then attach bidder submissions for source-backed first-level scrutiny.</div>",
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
    status_markup(status, tender_root)
    render_bidder_requirements_preview(tender_root)

    if not has_bidder_documents(tender_root):
        if status.get("status") == "requirements_ready":
            st.info("Next: enter the number of bidders and upload bidder documents in the sidebar.")
        maybe_auto_refresh(status, tender_root)
        return

    tabs = st.tabs(["Agent 1: Identity", "Agent 2: Bidder Requirements", "Agent 3: Turnover", "Downloads"])
    with tabs[0]:
        render_identity_tab(tender_root)
    with tabs[1]:
        render_documents_tab(tender_root)
    with tabs[2]:
        render_turnover_tab(tender_root)
    with tabs[3]:
        render_downloads_tab(tender_root)

    maybe_auto_refresh(status, tender_root)


if __name__ == "__main__":
    # Streamlit's control-flow signals (st.rerun/st.stop) subclass BaseException, so this
    # guard surfaces real errors as a friendly message without swallowing reruns.
    try:
        render_main()
    except Exception as exc:  # noqa: BLE001 - last-resort UI error boundary
        st.error("The app hit an unexpected error. Details are shown below.")
        st.exception(exc)
