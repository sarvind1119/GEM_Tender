# Web App Guide

## Purpose

The Streamlit app wraps the local pipeline in a user-friendly upload and review interface.

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements_web.txt
.\run_app.ps1
```

The launcher deliberately uses only `.venv\Scripts\python.exe` and reports an
actionable setup message if that environment is missing.

## Setup Flow

1. Open **Tender Setup** and upload the GeM tender PDF.
2. Analyze and inspect the extracted tender requirements.
3. Enter the number of bids received.
4. Upload all PDF submissions for each bidder.
5. Process the bidders, then continue to **Review Bidders**.

The app creates a local run folder:

```text
app_data/tenders/<run_id>/
```

## Processing

Processing runs in the background. The primary workspace shows the current
status and progress. Technical details are available under **Advanced
Diagnostics**, including:

- current pipeline status
- stage-level progress
- processing logs
- failed-stage message if any agent fails

## Legacy Agent Tabs

The following agent-oriented result tabs exist only in the temporary legacy
interface launched with `.\run_app.ps1 -Legacy`.

### Agent 1: Identity

Shows bidder-wise PAN, GSTIN, identity validation status, and source file/page columns.

### Agent 2: Bidder Requirements

Shows one row per bidder. Tender document requirements can receive presence-style checks; criteria and conditions that need semantic review remain `Needs Review`.

### Agent 3: Turnover

Shows bidder turnover and OEM turnover review status. The reference panel shows:

- source document name
- page number
- evidence text snippet
- review-safe status

### Downloads

Provides quick access to key Excel outputs such as manifest, text index, required-document attributes, bidder matrix, and turnover matrix.

## Reviewer-First Workflow

The default app now organizes work by task rather than processing agent:

1. **Tender Setup** — upload or reopen a tender and process bidder submissions.
2. **Tender Requirements** — inspect system-assessable and manual-review clauses.
3. **Review Bidders** — select one bidder, review normalized findings, record draft decisions, and inspect evidence.
4. **Export & Audit** — download the normalized reviewed workbook, local activity log, and immutable source artifacts.

Requirement decisions are keyed by a stable content fingerprint rather than the
positional `REQ-*` identifier. Pipeline outputs remain read-only. Draft review
state and activity events are stored locally inside the gitignored tender
workspace.

Evidence is explicitly labelled as an authoritative pipeline citation, suggested
page, document candidate, reviewer-supplied reference, or unavailable. Suggested
pages are navigation aids and must not be treated as extracted citations.

The legacy interface remains available during the first pilot:

```powershell
.\run_app.ps1 -Legacy
```

## Legacy Reviewer Edits

The legacy app supports reviewer-editable tables for:

- document matrix notes/decisions
- turnover review notes/decisions

These legacy tables can be saved and downloaded as Excel. The default app writes
human decisions to the unified review store and exports a normalized reviewed
workbook without modifying pipeline matrices.

## Local Data

All uploaded documents and generated outputs remain local under `app_data/`. This folder is ignored by Git.
