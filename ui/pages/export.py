from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any

import streamlit as st
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill

from tools.pipeline_runner import read_status
from ui.adapter import load_review_items
from ui.common import download_path
from ui.review_state import audit_path, export_rows, load_state


def _excel_safe(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False)
    return ILLEGAL_CHARACTERS_RE.sub(" ", str(value))


def _audit_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _review_workbook(rows: list[dict[str, Any]], activity: list[dict[str, Any]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Reviewed Findings"
    headers = list(rows[0]) if rows else [
        "bidder_id",
        "requirement_fingerprint",
        "requirement_text",
        "reviewer_outcome",
    ]
    sheet.append(headers)
    for row in rows:
        sheet.append([_excel_safe(row.get(header, "")) for header in headers])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    activity_sheet = workbook.create_sheet("Review Activity")
    activity_headers = sorted({key for row in activity for key in row}) or ["ts", "event_type"]
    activity_sheet.append(activity_headers)
    for row in activity:
        activity_sheet.append([_excel_safe(row.get(header, "")) for header in activity_headers])
    activity_sheet.freeze_panes = "A2"
    activity_sheet.auto_filter.ref = activity_sheet.dimensions

    header_fill = PatternFill("solid", fgColor="0F766E")
    header_font = Font(color="FFFFFF", bold=True)
    for target in (sheet, activity_sheet):
        for cell in target[1]:
            cell.fill = header_fill
            cell.font = header_font
        for row in target.iter_rows():
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for column in target.columns:
            letter = column[0].column_letter
            width = min(55, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
            target.column_dimensions[letter].width = width

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def render(tender_root: Path | None) -> None:
    st.subheader("Export and audit")
    st.caption("Download normalized reviewer work and the original immutable pipeline artifacts.")
    if tender_root is None:
        st.info("Open a tender workspace first.")
        return

    items = load_review_items(tender_root)
    state = load_state(tender_root)
    rows = export_rows(items, state)
    activity = _audit_rows(audit_path(tender_root))
    decided = sum(1 for row in rows if row.get("reviewer_outcome"))
    completed = sum(
        1
        for value in state.get("bidder_reviews", {}).values()
        if value.get("status") == "completed"
    )
    col1, col2, col3 = st.columns(3)
    col1.metric("Normalized findings", len(rows))
    col2.metric("Decisions drafted", decided)
    col3.metric("Bidders completed", completed)

    workbook = _review_workbook(rows, activity)
    st.download_button(
        "Download reviewed scrutiny workbook",
        workbook,
        file_name=f"{tender_root.name}_reviewed_scrutiny.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        width="stretch",
    )
    if audit_path(tender_root).exists():
        st.download_button(
            "Download local review activity JSONL",
            audit_path(tender_root).read_bytes(),
            file_name="review_audit.jsonl",
            mime="application/json",
            width="stretch",
        )
    st.caption(
        "Reviewer identity is self-declared. This local activity log is append-only during normal application use, "
        "but it is not authentication-backed or tamper-evident."
    )

    st.divider()
    st.markdown("**Original pipeline artifacts**")
    output = tender_root / "05_Extraction_Output"
    downloads = (
        ("Document manifest", output / "document_manifest.xlsx"),
        ("Tender requirements", output / "05_tender_requirements" / "bidder_requirements.xlsx"),
        ("Bidder requirements matrix", output / "06_bidder_review_matrix" / "bidder_document_review_matrix.xlsx"),
        ("Turnover review matrix", output / "07_turnover_evaluation" / "turnover_review_matrix.xlsx"),
        ("Registry verification", output / "08_verification" / "verification_matrix.xlsx"),
    )
    left, right = st.columns(2)
    for index, (label, path) in enumerate(downloads):
        with left if index % 2 == 0 else right:
            download_path(
                path,
                f"Download {label}",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    with st.expander("Advanced diagnostics", expanded=False):
        status = read_status(tender_root)
        st.json(
            {
                "run_id": tender_root.name,
                "workspace": str(tender_root),
                "pipeline_status": status.get("status", "unknown"),
                "artifact_count": len(rows),
                "activity_events": len(activity),
            }
        )
        if status.get("logs"):
            for entry in status["logs"][-50:]:
                st.caption(f"{entry.get('ts', '')} — {entry.get('message', '')}")
