from __future__ import annotations

import threading
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

from tools.pipeline_runner import APP_DATA_ROOT, read_status, run_pipeline


APP_TITLE = "GeM Bid Scrutiny"


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
          --ink: #12223a;
          --muted: #5f6b7a;
          --line: #d8dee7;
          --teal: #0f766e;
          --teal-soft: #e9f5f2;
          --amber: #9a6700;
          --amber-soft: #fff7db;
          --red: #b42318;
          --red-soft: #fff0ee;
          --paper: #fbfaf7;
        }
        .stApp { background: var(--paper); color: var(--ink); }
        [data-testid="stSidebar"] {
          background: #f1f3f4;
          border-right: 1px solid var(--line);
        }
        .block-container {
          max-width: 1560px;
          padding-top: 3.65rem;
          padding-bottom: 2.5rem;
        }
        .gem-brand {
          color: var(--ink);
          font-size: 1.05rem;
          font-weight: 800;
          letter-spacing: -.01em;
          margin: .15rem 0 1rem;
        }
        .workspace-header {
          align-items: end;
          border-bottom: 1px solid var(--line);
          display: flex;
          gap: 1rem;
          justify-content: space-between;
          margin-bottom: 1rem;
          padding-bottom: .85rem;
        }
        .workspace-title {
          color: var(--ink);
          font-size: 1.45rem;
          font-weight: 750;
          letter-spacing: -.025em;
          line-height: 1.2;
          margin: 0;
        }
        .workspace-meta {
          color: var(--muted);
          font-size: .82rem;
          margin-top: .25rem;
        }
        .status-tag, .evidence-tag {
          border: 1px solid #9dcfc8;
          border-radius: 999px;
          color: var(--teal);
          display: inline-block;
          font-size: .74rem;
          font-weight: 750;
          padding: .25rem .55rem;
          white-space: nowrap;
        }
        .evidence-tag.suggested {
          background: var(--amber-soft);
          border-color: #e7c96c;
          color: var(--amber);
        }
        .evidence-tag.unavailable {
          background: var(--red-soft);
          border-color: #e5aaa5;
          color: var(--red);
        }
        .system-finding {
          border-left: 3px solid var(--teal);
          margin: .35rem 0 1rem;
          padding: .1rem .9rem;
        }
        .system-finding .label {
          color: var(--muted);
          font-size: .72rem;
          font-weight: 750;
          letter-spacing: .06em;
          text-transform: uppercase;
        }
        .system-finding .value {
          color: var(--ink);
          font-weight: 700;
          margin-top: .2rem;
        }
        .manual-strip {
          background: var(--amber-soft);
          border-left: 3px solid #d6a514;
          color: #5d4700;
          padding: .7rem .85rem;
        }
        div[data-testid="stMetric"] {
          background: transparent;
          border-top: 1px solid var(--line);
          padding-top: .55rem;
        }
        div[data-testid="stButton"] > button[kind="primary"] {
          background: var(--teal);
          border-color: var(--teal);
        }
        div[data-testid="stButton"] > button {
          border-radius: .35rem;
        }
        [data-testid="stExpander"] {
          background: rgba(255,255,255,.42);
          border-color: var(--line);
        }
        .review-help {
          color: var(--muted);
          font-size: .82rem;
          line-height: 1.45;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def run_folders() -> list[Path]:
    if not APP_DATA_ROOT.exists():
        return []
    return sorted((path for path in APP_DATA_ROOT.iterdir() if path.is_dir()), reverse=True)


def friendly_run_name(path: Path) -> str:
    status = read_status(path)
    tender_id = str(status.get("tender_id") or path.name)
    base = tender_id.rsplit("_20", 1)[0].replace("_", " ").strip()
    state = str(status.get("status") or "not started").replace("_", " ")
    updated = str(status.get("updated_at") or "")
    stamp = updated.replace("T", " ")[:16] if updated else path.name.rsplit("_", 2)[-2]
    return f"{base} · {state} · {stamp}"


def bidder_count(tender_root: Path) -> int:
    bidder_root = tender_root / "03_Bidder_Submissions"
    if not bidder_root.exists():
        return 0
    return len([path for path in bidder_root.iterdir() if path.is_dir()])


def has_bidder_documents(tender_root: Path) -> bool:
    bidder_root = tender_root / "03_Bidder_Submissions"
    return bidder_root.exists() and any(bidder_root.rglob("*.pdf"))


def start_background_pipeline(run_id: str, tender_root: Path) -> None:
    thread = threading.Thread(
        target=run_pipeline,
        kwargs={"tender_id": run_id, "tender_root": tender_root, "engine": "auto"},
        daemon=True,
    )
    thread.start()


def render_workspace_header(tender_root: Path | None) -> None:
    if tender_root is None:
        st.markdown(
            """
            <div class="workspace-header">
              <div>
                <div class="workspace-title">Tender setup</div>
                <div class="workspace-meta">Create or open a local scrutiny workspace.</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return
    status = read_status(tender_root)
    state = escape(str(status.get("status") or "not started").replace("_", " ").title())
    updated = escape(str(status.get("updated_at") or ""))
    count = bidder_count(tender_root)
    title = escape(tender_root.name.rsplit("_20", 1)[0].replace("_", " "))
    st.markdown(
        f"""
        <div class="workspace-header">
          <div>
            <div class="workspace-title">{title}</div>
            <div class="workspace-meta">{count} bidder{"s" if count != 1 else ""} · Last update {updated or "not available"}</div>
          </div>
          <span class="status-tag">{state}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def status_summary(status: dict[str, Any]) -> None:
    if not status:
        st.info("This tender has not been processed yet.")
        return
    steps = status.get("steps", [])
    completed = sum(1 for step in steps if step.get("status") == "Completed")
    st.progress(completed / max(len(steps), 1), text=f"{completed}/{len(steps)} processing stages complete")
    if status.get("error"):
        st.error(str(status["error"]))
    with st.expander("Advanced diagnostics", expanded=False):
        st.write(f"Run status: `{status.get('status', 'unknown')}`")
        st.write(f"Active stage: `{status.get('active_step') or 'none'}`")
        for item in status.get("logs", [])[-50:]:
            st.caption(f"{item.get('ts', '')} — {item.get('message', '')}")


def download_path(path: Path, label: str, mime: str) -> None:
    if path.exists():
        st.download_button(
            label,
            path.read_bytes(),
            file_name=path.name,
            mime=mime,
            width="stretch",
        )
