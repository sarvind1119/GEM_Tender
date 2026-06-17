# Project Overview

## Problem Statement

On GeM, each tender has its own eligibility conditions and required-document list. Bidders submit multiple supporting PDFs such as GST certificates, PAN proofs, turnover certificates, OEM authorizations, experience documents, and declarations. Officials currently inspect these documents manually.

This project builds a first-level scrutiny assistant that reads tender and bidder documents, extracts deterministic identity and document-presence evidence, and produces source-backed review matrices for officials.

## Current Scope

The current prototype focuses on one local, manually uploaded tender package at a time:

- Upload tender documents and bidder-wise PDF submissions.
- Extract native PDF text and OCR text page-wise.
- Extract PAN, GSTIN, bidder name, and identity evidence.
- Extract `Document required from seller` attributes from the tender.
- Build a bidder-wise required-document review matrix.
- Extract and review bidder/OEM turnover evidence.
- Display outputs in a Streamlit app and export Excel/JSON artifacts.

## Phase 1 Roadmap

Phase 1 is manual and controlled:

1. Manually collect tender and bidder documents.
2. Organize them by tender and bidder.
3. Extract text through native PDF extraction and OCR.
4. Run deterministic identity and presence checks.
5. Use LLM assistance only for source-backed semantic review such as turnover interpretation.
6. Keep human review mandatory for final decisions.

## Phase 2 Roadmap

Phase 2 is deferred until legal/security approval:

- GeM document collection automation.
- Chrome extension or official API/bulk download integration.
- Server-side OCR execution.
- API-based PAN/GSTIN verification.
- Stronger audit trail and multi-user review.

## Safety Principles

- The system assists officials; it does not replace final decision-making.
- It should not auto-reject bidders.
- Every positive finding should carry source file and page evidence.
- Unclear, missing, or semantic items should remain `Needs Review`.
- External API use must be explicit and approved.
