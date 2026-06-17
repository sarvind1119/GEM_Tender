# Web App Guide

## Purpose

The Streamlit app wraps the local pipeline in a user-friendly upload and review interface.

## Run

```powershell
streamlit run app.py
```

If Streamlit is not installed:

```powershell
python -m pip install -r requirements_web.txt
```

## Upload Flow

1. Upload the GeM tender PDF in the left panel.
2. Enter the number of bids received.
3. Upload all PDF submissions for each bidder.
4. Click `Process`.

The app creates a local run folder:

```text
app_data/tenders/<run_id>/
```

## Processing

Processing runs in the background. The app shows:

- current pipeline status
- stage-level progress
- processing logs
- failed-stage message if any agent fails

## Result Tabs

### Agent 1: Identity

Shows bidder-wise PAN, GSTIN, identity validation status, and source file/page columns.

### Agent 2: Required Documents

Shows one row per bidder. Each required document extracted from the tender becomes a column group with status, source files, document IDs, and reviewer notes.

### Agent 3: Turnover

Shows bidder turnover and OEM turnover review status. The reference panel shows:

- source document name
- page number
- evidence text snippet
- review-safe status

### Downloads

Provides quick access to key Excel outputs such as manifest, text index, required-document attributes, bidder matrix, and turnover matrix.

## Reviewer Edits

The app supports reviewer-editable tables for:

- document matrix notes/decisions
- turnover review notes/decisions

Reviewed tables can be saved and downloaded as Excel.

## Local Data

All uploaded documents and generated outputs remain local under `app_data/`. This folder is ignored by Git.
