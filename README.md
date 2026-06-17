# First-Level Scrutiny System for GeM Bids

This project is a local, human-in-the-loop prototype for first-level scrutiny of bidder documents submitted against GeM tenders. It extracts text from tender and bidder PDFs, identifies bidder identity fields, extracts tender-required documents, builds a bidder-wise review matrix, and evaluates turnover evidence with source-backed references.

The detailed project note is maintained in [GeM_Bid_Checking_Final_Understandingv2.md](GeM_Bid_Checking_Final_Understandingv2.md).

## Status

The current prototype includes:

- A Streamlit web app for uploading one tender and bidder-wise PDF submissions.
- OCR/native text extraction with page-level JSON and text outputs.
- PAN/GSTIN extraction, validation, and bidder identity summaries.
- Tender-side extraction of `Document required from seller`.
- Bidder-wise required-document review matrix.
- Turnover requirement extraction and LLM-assisted review with source document, page, and evidence snippet.
- Excel and JSON outputs for review and future API/UI integration.

This system assists officials. It does not replace final human procurement decision-making.

## Agent Workflow

### Agent 1: Identity Extraction

Reads all tender and bidder PDFs, extracts native/selectable text, applies OCR where needed, and identifies bidder-side PAN, GSTIN, bidder name, source file, page number, and validation status.

### Agent 2: Required Document Matrix

Reads only tender-side text to extract the GeM field `Document required from seller`, converts each extracted item into a review attribute, and builds a bidder-wise document presence matrix.

### Agent 3: Turnover Review

Extracts bidder and OEM turnover thresholds from the tender, finds likely bidder-side turnover evidence, and produces conservative suggestions such as `Likely Meets - Needs Human Review`, always with evidence references.

## Safety Principle

Procurement scrutiny is audit-sensitive. The prototype uses conservative statuses and keeps human review mandatory for unclear, semantic, or LLM-assisted findings. It should not auto-reject, auto-disqualify, or make final eligibility decisions.

Real tender documents, bidder submissions, generated OCR outputs, app uploads, logs, and API keys are intentionally excluded from GitHub.

## Repository Structure

```text
.
  app.py
  requirements_web.txt
  tools/
    pipeline_runner.py
    run_phase1_identity_extraction.py
    extract_tender_required_documents.py
    build_bidder_review_matrix.py
    evaluate_turnover_requirements.py
    .env.example
  docs/
    PROJECT_OVERVIEW.md
    PIPELINE.md
    WEB_APP.md
    SECURITY_AND_DATA_GOVERNANCE.md
  GeM_Bid_Checking_Final_Understandingv2.md
```

## Install

```powershell
python -m pip install -r requirements_web.txt
```

The OCR pipeline also requires the existing local OCR/PDF stack used in the pilot, including Tesseract/Poppler and optional PaddleOCR.

## Configure Groq

Create `tools/.env` locally. Do not commit it.

```env
GROQ_API_KEY=your_key_here
TURNOVER_LLM_MODEL=llama-3.3-70b-versatile
```

If no API key is configured, turnover evaluation falls back to conservative local logic.

## Run The Web App

```powershell
streamlit run app.py
```

Upload the tender PDF, enter the number of bidders, upload bidder-wise documents, and click `Process`.

Each local run is stored under:

```text
app_data/tenders/<run_id>/
```

## Documentation

- [Project overview](docs/PROJECT_OVERVIEW.md)
- [Pipeline details](docs/PIPELINE.md)
- [Web app guide](docs/WEB_APP.md)
- [Security and data governance](docs/SECURITY_AND_DATA_GOVERNANCE.md)
- [Detailed project understanding](GeM_Bid_Checking_Final_Understandingv2.md)

## GitHub Data Policy

Do not commit:

- real tender PDFs
- bidder submissions
- PAN/GSTIN/financial documents
- generated OCR/extraction outputs
- local app uploads
- logs
- `.env` files or API keys

A sanitized demo dataset can be added later only after manual redaction and approval.
