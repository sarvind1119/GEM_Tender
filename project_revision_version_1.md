# Project Revision Version 1

Date: 2026-07-06

Project: First-Level Scrutiny System for GeM Bids

## 1. Project Summary

This project is a local, human-in-the-loop prototype for first-level scrutiny of bidder documents submitted against GeM tenders.

The system reads tender documents and bidder PDF submissions, extracts text through native PDF extraction and OCR, identifies important bidder identity fields such as PAN and GSTIN, extracts tender-side bidder requirements, builds bidder-wise review matrices, and evaluates turnover evidence with source references.

The tool is designed as a scrutiny assistant. It does not make final procurement decisions. Officials remain responsible for final acceptance, rejection, clarification, and override decisions.

## 2. Original Requirement

The requirement came from a workflow where officials manually download GeM tender documents and bidder submissions, then check whether each bidder has submitted the required documents and satisfies the tender conditions.

The requested system should:

1. Accept tender documents and bidder-wise uploaded PDF submissions.
2. Extract text from both digital/selectable PDFs and scanned PDFs.
3. Extract key identity fields such as bidder/vendor name, PAN, GSTIN, and other identifiable numbers.
4. Validate deterministic fields where possible, especially PAN format, GSTIN format, GSTIN checksum, and GSTIN-to-PAN consistency.
5. Read the tender requirement section, especially the GeM field named `Document required from seller`.
6. Detect whether bidder submissions contain likely required documents such as GST certificate, PAN proof, turnover certificate, OEM authorization, experience certificate, MII/local content declaration, and similar documents.
7. Build a bidder-wise compliance or review matrix where rows/columns show each requirement and each bidder's status.
8. Route unclear, semantic, low-confidence, or eligibility-heavy items to manual review.
9. Support source-backed review by showing document name, page number, extracted value, and evidence snippet.
10. Produce Excel outputs for officials and JSON outputs for future UI/API integration.
11. Later, after legal/security approval, support automated GeM document collection through a Chrome extension, official API, or other approved channel.

## 3. Scope Split

The project is intentionally split into phases.

### Phase 1: Manual MVP

Phase 1 is the current implemented prototype. Documents are manually downloaded and uploaded/organized. The system performs OCR/text extraction, deterministic identity extraction, required-document extraction, document presence matching, and turnover review.

### Phase 1.5: Semantic Eligibility Review

This is partially started through turnover evaluation. The system can use an OpenAI-compatible LLM through Groq or another configured provider, but it falls back to conservative local logic when no API key is available.

### Phase 2: Automated Collection

This is deferred. The idea is to use a Chrome extension, official GeM API, or another approved route to collect tender and bidder files automatically. This requires security, legal, and data-governance approval before implementation.

## 4. What Has Been Done So Far

### 4.1 Project Understanding And Documentation

The project has a written understanding and technical documentation:

- `GeM_Bid_Checking_Final_Understanding.md`
- `GeM_Bid_Checking_Final_Understandingv2.md`
- `README.md`
- `WEB_APP_README.md`
- `docs/PROJECT_OVERVIEW.md`
- `docs/PIPELINE.md`
- `docs/WEB_APP.md`
- `docs/SECURITY_AND_DATA_GOVERNANCE.md`

These documents define the problem, MVP scope, pipeline flow, web app usage, security rules, and future roadmap.

### 4.2 Pilot Dataset Structure

A pilot tender workspace exists under:

```text
Tender_01_VacuumFlask/
```

It follows this structure:

```text
Tender_01_VacuumFlask/
  01_Tender_Document/
  02_Eligibility_and_Terms/
  03_Bidder_Submissions/
  04_Control_Artifacts/
  05_Extraction_Output/
  06_Compliance_Matrix/
  07_Audit_Log/
```

The pilot includes tender-side files, bidder-side submissions for 3 bidders, control artifacts, extraction outputs, compliance matrix output, and an audit log template.

### 4.3 Streamlit Web App

A local Streamlit app has been built in:

```text
app.py
```

The app supports:

1. Uploading one or more tender PDFs.
2. Running tender requirement extraction before bidder upload.
3. Showing extracted bidder requirements from the tender.
4. Entering number of bidders.
5. Uploading bidder-wise PDF documents.
6. Starting bidder processing in the background.
7. Showing pipeline status, stage progress, logs, and failure messages.
8. Displaying results in tabs:
   - Agent 1: Identity
   - Agent 2: Bidder Requirements
   - Agent 3: Turnover
   - Downloads
9. Saving reviewer edits for bidder document matrix and turnover review matrix.
10. Downloading generated Excel outputs.

The app stores local runs under:

```text
app_data/tenders/<run_id>/
```

### 4.4 Pipeline Runner

The web app is connected to a pipeline runner:

```text
tools/pipeline_runner.py
```

It handles:

1. Creating run IDs.
2. Creating upload workspace folders.
3. Saving tender and bidder uploads.
4. Tracking pipeline status in `pipeline_status.json`.
5. Running pipeline stages in order.
6. Writing logs and stage progress.
7. Marking failed runs.
8. Writing reviewed Excel workbooks from reviewer edits.

### 4.5 Agent 1: OCR, Text Extraction, PAN/GSTIN, Identity

Implemented in:

```text
tools/run_phase1_identity_extraction.py
```

This stage does the following:

1. Finds all PDFs in the tender workspace.
2. Builds a document manifest with document IDs, paths, bidder IDs, bidder names, document side, document type guesses, and hashes.
3. Extracts native/selectable text from PDFs.
4. Runs OCR where required or useful.
5. Supports Tesseract and optional PaddleOCR.
6. Chooses the best text per page from native text, OCR text, or combined text.
7. Writes page-wise JSON and text outputs.
8. Extracts PAN and GSTIN candidates with regex patterns that tolerate OCR spacing and separators.
9. Normalizes PAN and GSTIN values.
10. Validates PAN format.
11. Validates GSTIN format, state code, and checksum.
12. Cross-checks GSTIN embedded PAN against extracted PAN.
13. Derives PAN from validated GSTIN when direct PAN is not found, while marking it for review.
14. Builds bidder identity summaries.
15. Writes validation outputs and logs.

Main outputs include:

```text
05_Extraction_Output/document_manifest.xlsx
05_Extraction_Output/document_manifest.json
05_Extraction_Output/01_text_extraction/
05_Extraction_Output/02_identity_extraction/
05_Extraction_Output/03_validation/
05_Extraction_Output/04_logs/
```

### 4.6 Agent 2A: Tender Requirement Extraction

Implemented in:

```text
tools/extract_tender_required_documents.py
```

This stage does the following:

1. Reads only tender-side chosen text.
2. Builds a consolidated text index.
3. Searches for `Document required from seller` and related label aliases.
4. Extracts the requirement field block from the tender.
5. Splits the block into individual requirement items.
6. Classifies requirements into categories such as experience, past performance, financial turnover, OEM authorization, OEM turnover, ATC reference, declaration, technical condition, or unknown.
7. Creates structured requirement attributes.
8. Adds condition rows for important tender conditions found outside the direct document-required field.
9. Writes bidder requirement previews for display in the web app.

For the pilot workspace, this stage produced:

- 243 text index rows.
- 1 tender-side requirement field block.
- 6 extracted requirement rows.
- 17 tender-side pages scanned for requirement extraction.
- 226 bidder-side pages ignored during tender requirement extraction.
- No validation issues in the extraction notes.

### 4.7 Agent 2B: Bidder Review Matrix

Implemented in:

```text
tools/build_bidder_review_matrix.py
```

This stage does the following:

1. Reads the document manifest.
2. Reads bidder identity summary.
3. Reads tender requirement attributes.
4. Builds one row per bidder.
5. Adds identity columns such as PAN, GSTIN, source file/page, and review flags.
6. Converts each tender requirement into matrix columns.
7. Uses document type and filename keyword matching to find likely source documents.
8. Marks clearly matched presence checks as `Present`.
9. Marks unclear, semantic, ATC-dependent, or unmatched items as `Needs Review`.
10. Writes Excel and JSON matrix outputs.

For the pilot workspace, this stage produced:

- 3 bidder rows.
- 6 required document/condition groups.
- 40 matrix columns.
- Status vocabulary: `Present`, `Needs Review`.
- No validation issues in matrix notes.

### 4.8 Agent 3: Turnover Evaluation

Implemented in:

```text
tools/evaluate_turnover_requirements.py
```

This stage does the following:

1. Reads tender-side text index.
2. Extracts bidder minimum average annual turnover requirement.
3. Extracts OEM average turnover requirement.
4. Finds likely bidder-side turnover evidence documents.
5. Extracts amount candidates from turnover evidence text.
6. Builds compact evidence snippets.
7. Redacts sensitive identifiers before API calls.
8. Uses an OpenAI-compatible LLM if configured.
9. Uses conservative offline fallback if no API key is configured.
10. Builds bidder-wise turnover review matrix.
11. Writes tender turnover requirements, evidence rows, LLM/fallback results, matrix, and notes.

For the pilot workspace, this stage produced:

- 2 turnover requirement types.
- 5 evidence rows.
- 6 LLM/fallback result rows.
- 3 review matrix rows.
- Provider used: offline fallback.
- API attempted: false.
- No validation issues in turnover notes.

Turnover statuses are intentionally conservative:

- `Likely Meets - Needs Human Review`
- `Likely Does Not Meet - Needs Human Review`
- `Unclear - Needs Human Review`
- `Evidence Not Found - Needs Human Review`

### 4.9 Output Artifacts

The pipeline writes both Excel and JSON outputs. Important output folders are:

```text
05_Extraction_Output/
  document_manifest.xlsx/json
  01_text_extraction/
    all_document_text_index.xlsx/json
    page_json/
    native_text/
    ocr_text/
    chosen_text/
  02_identity_extraction/
    pan_gstin_candidates.xlsx/json
    bidder_identity_summary.xlsx/json
  03_validation/
    validation_results.xlsx/json
  04_logs/
    dependency_check.xlsx/json
    processing_log.jsonl
    errors.xlsx
  05_tender_requirements/
    document_required_field_blocks.xlsx/json
    required_document_attributes.xlsx/json
    bidder_requirements.xlsx/json
    extraction_notes.json
  06_bidder_review_matrix/
    bidder_document_review_matrix.xlsx/json
    bidder_document_review_matrix_notes.xlsx/json
  07_turnover_evaluation/
    tender_turnover_requirements.xlsx/json
    bidder_turnover_evidence.xlsx/json
    turnover_llm_results.xlsx/json
    turnover_review_matrix.xlsx/json
    turnover_notes.json
```

### 4.10 App Run Evidence

At least one local app run has completed end-to-end under:

```text
app_data/tenders/
```

The completed run shows all major stages completed:

1. Agent 1 identity extraction completed.
2. Agent 2 requirement extraction completed.
3. Agent 2 bidder matrix completed.
4. Agent 3 turnover evaluation completed.
5. Pipeline status marked `completed`.

Several additional tender requirement preview runs also exist under `app_data/tenders/`.

### 4.11 Security And Data Governance

Security guidance has been documented in:

```text
docs/SECURITY_AND_DATA_GOVERNANCE.md
```

Current rules:

1. Do not commit real tender PDFs.
2. Do not commit bidder submissions.
3. Do not commit generated OCR/extraction outputs containing real bidder data.
4. Do not commit `tools/.env` or API keys.
5. Treat PAN, GSTIN, financial certificates, addresses, and commercial records as sensitive procurement data.
6. Use external APIs only with approval.
7. Send only redacted snippets to LLM APIs, not full bid bundles.
8. Keep final human decision authority with officials.

`.gitignore` has been configured to keep local sensitive data and generated outputs out of Git.

## 5. How The System Works Step By Step

### Step 1: Prepare Documents

For a manual pilot, collect:

1. Tender PDF or tender bundle.
2. Terms and conditions.
3. Eligibility criteria or ATC document.
4. Bidder-wise submitted PDFs.

The expected folder contract is:

```text
<tender_root>/
  01_Tender_Documents/
  03_Bidder_Submissions/
    Bidder_01/
    Bidder_02/
  05_Extraction_Output/
```

The Streamlit app creates this structure automatically under `app_data/tenders/<run_id>/`.

### Step 2: Upload Tender In Web App

Run:

```powershell
.\run_app.ps1
```

The launcher uses the bundled Python runtime if available:

```powershell
C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
```

Otherwise it uses normal `python`.

In the app:

1. Upload the tender PDF.
2. Click `Analyze Tender Requirements`.
3. The app creates a run folder.
4. The app runs tender text extraction and requirement extraction.
5. The extracted bidder requirements are shown before bidder upload.

### Step 3: Extract Tender Text And Requirements

The preview flow runs:

1. Agent 1 only on tender-side documents to extract page text.
2. Agent 2A to extract bidder requirements from the tender.

This allows the official to check what the tender is asking for before uploading bidder documents.

### Step 4: Upload Bidder Documents

In the sidebar:

1. Enter the number of bidders.
2. Optionally enter bidder names.
3. Upload PDFs for each bidder.
4. Click `Process Bidders`.

The app saves files under:

```text
03_Bidder_Submissions/Bidder_XX/
```

### Step 5: Run Full Pipeline

The full pipeline runs these stages in order:

1. Agent 1: OCR, text extraction, PAN/GSTIN extraction, identity summary.
2. Agent 2A: tender-side bidder requirement extraction.
3. Agent 2B: bidder-wise document review matrix.
4. Agent 3: bidder and OEM turnover evaluation.

The pipeline writes progress to:

```text
pipeline_status.json
```

### Step 6: Review Identity

The app reads:

```text
05_Extraction_Output/02_identity_extraction/bidder_identity_summary.json
```

The reviewer sees bidder-wise:

1. Bidder ID.
2. Bidder name.
3. PAN.
4. PAN source file/page.
5. PAN status.
6. GSTIN.
7. GSTIN source file/page.
8. GSTIN status.
9. GSTIN-to-PAN match status.
10. Needs-human-review flag.

### Step 7: Review Bidder Requirements

The app reads:

```text
05_Extraction_Output/06_bidder_review_matrix/bidder_document_review_matrix.json
```

The reviewer sees a bidder-wise matrix. Presence-style checks can be marked `Present` when the system finds likely source documents. Semantic or unclear checks remain `Needs Review`.

Reviewer edits can be saved to:

```text
bidder_document_review_matrix_reviewed.json
bidder_document_review_matrix_reviewed.xlsx
```

### Step 8: Review Turnover

The app reads:

```text
05_Extraction_Output/07_turnover_evaluation/turnover_review_matrix.json
```

The reviewer sees:

1. Bidder turnover threshold.
2. Extracted average, where available.
3. Review-safe status.
4. Source file.
5. Source page.
6. Evidence text.
7. OEM turnover threshold.
8. OEM turnover evidence and status.
9. LLM/fallback confidence.

Reviewer edits can be saved to:

```text
turnover_review_matrix_reviewed.json
turnover_review_matrix_reviewed.xlsx
```

### Step 9: Download Outputs

The Downloads tab exposes important Excel outputs:

1. Document manifest.
2. Text index.
3. Bidder requirements preview.
4. Bidder requirement attributes.
5. Bidder requirements matrix.
6. Turnover review matrix.
7. LLM/fallback details.

## 6. Current Technical Stack

The current web dependencies are listed in:

```text
requirements_web.txt
```

Main libraries:

- Streamlit
- python-dotenv
- pandas
- openpyxl
- pillow
- pypdf
- pdf2image
- PyMuPDF

OCR/document processing can additionally use local Tesseract, Poppler, and optional PaddleOCR depending on the machine setup.

Turnover LLM integration uses environment variables in `tools/.env`:

```env
GROQ_API_KEY=your_key_here
TURNOVER_LLM_MODEL=llama-3.3-70b-versatile
```

If no key is configured, turnover review still runs with conservative offline fallback.

## 7. Current Status

As of this revision:

1. Requirement understanding is documented.
2. Pilot folder structure is created.
3. Control artifacts exist for the pilot.
4. OCR/text extraction is implemented.
5. PAN/GSTIN extraction and validation are implemented.
6. Tender requirement extraction is implemented.
7. Bidder-wise document matrix generation is implemented.
8. Turnover requirement extraction and evidence review are implemented.
9. Streamlit upload/review/download app is implemented.
10. Reviewer-edit save flow is implemented for document matrix and turnover matrix.
11. Local app run storage is implemented.
12. Security/data governance documentation is written.
13. GitHub exclusion policy is documented and `.gitignore` is configured.

## 8. Known Gaps And Pending Work

1. Full semantic eligibility reasoning is not complete for all tender conditions.
2. ATC clause expansion is deferred; ATC-referenced certificates remain `Needs Review`.
3. Experience certificate semantic matching is not fully automated.
4. Past performance matching is mostly presence/keyword based.
5. Vendor name fuzzy matching across documents is not yet a strong validation gate.
6. Certificate date validity and expiry checks need expansion.
7. Live PAN/GST API verification is not implemented and needs official approval.
8. Multi-user audit trail is not fully implemented; only templates/reviewer outputs exist.
9. Ground-truth comparison and measurable accuracy reports need to be formalized.
10. Chrome extension or automated GeM collection is not implemented.
11. Server/GPU deployment is not implemented.
12. API/backend service layer is not implemented; current app is local Streamlit.
13. Git status could not be checked during this revision because Windows reported repository ownership as a safe-directory issue.

## 9. Recommended Next Steps

1. Freeze Phase 1 scope around one complete tender and 3 or more bidders.
2. Prepare a clean ground-truth sheet for PAN, GSTIN, bidder name, source page, and required-document presence.
3. Compare system outputs against ground truth and calculate:
   - coverage
   - exact PAN/GSTIN accuracy
   - source page correctness
   - false `Present` rate
   - manual review routing accuracy
4. Expand requirement matching for ATC clauses.
5. Add experience and past-performance semantic review as the next LLM-assisted slice.
6. Add certificate validity/date extraction.
7. Add append-only audit logging for reviewer decisions and overrides.
8. Confirm whether official GST/PAN verification APIs can be used.
9. Only after approval, start Phase 2 document collection automation.

## 10. Important Safety Principle

The system should never silently reject or qualify a bidder. It should only assist first-level scrutiny by producing structured evidence, conservative statuses, and reviewer-editable matrices.

The safe rule is:

- Mark `Present` only for high-confidence deterministic or filename/type-based presence evidence.
- Keep unclear, semantic, missing, unmatched, or low-confidence cases as `Needs Review`.
- Always preserve source file, page number, and evidence snippet wherever available.
- Keep final decision authority with the human reviewer.

