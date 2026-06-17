# Pipeline Details

## Folder Contract

The pipeline expects each tender workspace to follow this structure:

```text
<tender_root>/
  01_Tender_Documents/
    tender.pdf
  03_Bidder_Submissions/
    Bidder_01/
      bidder files.pdf
    Bidder_02/
      bidder files.pdf
  05_Extraction_Output/
```

The web app creates this structure automatically under:

```text
app_data/tenders/<run_id>/
```

## Agent Sequence

The pipeline runner executes the agents sequentially because later steps depend on earlier outputs.

1. `run_phase1_identity_extraction.py`
   - builds the document manifest
   - extracts native text and OCR text page-wise
   - chooses best text per page
   - extracts PAN/GSTIN candidates
   - writes bidder identity summary and validation results

2. `extract_tender_required_documents.py`
   - reads tender-side chosen text
   - extracts `Document required from seller`
   - creates structured required-document attributes
   - creates the consolidated text index

3. `build_bidder_review_matrix.py`
   - joins the document manifest, identity summary, and tender requirement attributes
   - builds one row per bidder with document presence status columns

4. `evaluate_turnover_requirements.py`
   - extracts bidder and OEM turnover thresholds
   - finds likely turnover evidence documents
   - calls an OpenAI-compatible LLM when configured
   - falls back to conservative local logic when no API is available

## Main Outputs

```text
05_Extraction_Output/
  document_manifest.xlsx/json
  01_text_extraction/
    all_document_text_index.xlsx/json
    page_json/
  02_identity_extraction/
    pan_gstin_candidates.xlsx/json
    bidder_identity_summary.xlsx/json
  03_validation/
    validation_results.xlsx/json
  05_tender_requirements/
    required_document_attributes.xlsx/json
  06_bidder_review_matrix/
    bidder_document_review_matrix.xlsx/json
  07_turnover_evaluation/
    turnover_review_matrix.xlsx/json
    turnover_llm_results.xlsx/json
```

## Status Vocabulary

The prototype avoids final procurement decisions. Typical statuses include:

- `Present`
- `Needs Review`
- `Extracted / Validated`
- `Likely Meets - Needs Human Review`
- `Likely Does Not Meet - Needs Human Review`
- `Unclear - Needs Human Review`
- `Evidence Not Found - Needs Human Review`

## Extending The Pipeline

Future agents should follow the same pattern:

- read existing JSON outputs rather than re-parsing PDFs
- produce Excel and JSON from the same underlying rows
- preserve source file and page references
- avoid final rejection or acceptance wording
- add reviewer-editable fields where officials need override capability
