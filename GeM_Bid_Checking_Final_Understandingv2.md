# GeM Bid-Document Checking System — Final Understanding

*Consolidated from the call transcript/summary and reviewed AI responses. This is the single reference to act from.*

---

## 1. Problem statement

On GeM, vendors submit bids against a tender, attaching supporting documents. Each tender carries its own **eligibility conditions** and a **required-document list** (in the memo / terms & conditions / eligibility section). Today an official opens every bidder's submission by hand and checks, line by line, whether each required document is present and each condition is met — slow and error-prone.

The task is to automate this **first-level scrutiny**: read the tender's requirements, read each bidder's documents (OCR / PDF extraction), extract and validate key fields, check the requirements, and produce a **vendor-wise compliance matrix** — while keeping a human in control of the final decision.

**One line:** an OCR + LLM-based GeM bid-eligibility checker that compares bidder documents against tender conditions and outputs a compliance checklist, with human-in-the-loop verification.

**Two phases (as the JD framed it):**
- **Phase 1 — manual:** download tenders + bidder docs by hand, build the extraction → validation → matching → matrix engine.
- **Phase 2 — automation:** a Chrome extension (riding the logged-in GeM session) to pull documents automatically, with OCR running server-side on the Nvidia/GPU box.

---

## 2. The decision that shapes the whole project

Split every requirement into two tiers. This turns one hard problem into one easy and one hard:

| Tier | Type | Examples | How to handle | Default decision |
|------|------|----------|---------------|------------------|
| **1** | Presence & format (deterministic) | GST cert present? PAN format valid? GSTIN checksum + API verify? Cert dated within validity? | Rules + APIs | **Auto-tick** when confident |
| **2** | Eligibility (semantic) | "≥3 years of similar work"? "Turnover ≥ ₹X"? "Work order matches scope"? | LLM reads requirement text against evidence text | **Needs Manual Review** + suggested answer + evidence |

Build **Tier 1 first** and prove it end-to-end. Tier 2 is the next slice — and it's an LLM/RAG task, not an OCR task. OCR only turns documents into text; the hard part is matching messy eligibility language to messy bidder evidence.

---

## 3. Immediate action (do this now — not build the full tool)

Prepare the **pilot dataset + requirement checklist**.

1. **Pick 3–5 sample tenders** — prefer completed/old ones; include varied document types so the team sees realistic inputs.
2. **Download manually**, per tender: tender document, terms & conditions, eligibility criteria, every bidder's submissions, any annexures/forms.
3. **Organize folders:**

```text
GeM_Bid_Checking_Pilot/
  Tender_01/
    01_Tender_Document/
    02_Eligibility_and_Terms/
    03_Bidder_Submissions/
      Bidder_01/
      Bidder_02/
      Bidder_03/
  Tender_02/
    ...
```

4. **Classify each PDF: scanned image vs digital (selectable text)** — this single fact decides whether you need OCR at all, and which tool. Note it per tender (often a tender bundle is mixed → you'll need both a PDF-text path and an OCR path).
5. **Hand-write the requirement checklist for ONE tender** — this is literally the left column of your matrix and the spec for what the extractor must find:

| Req ID | Tender requirement | Required document | Field to extract | Tier | Bidder 1 | Bidder 2 | Remarks |
|--------|--------------------|-------------------|------------------|------|----------|----------|---------|
| R1 | Valid GST registration | GST certificate | GSTIN | 1 | Y/N | Y/N | |
| R2 | PAN required | PAN card | PAN number | 1 | Y/N | Y/N | |
| R3 | Technical experience | Experience / work-order cert | Years, scope | 2 | Y/N | Y/N | |
| R4 | Financial capacity | CA cert / turnover proof | Turnover value | 2 | Y/N | Y/N | |

6. **Hand the pilot folder + checklist to the technical team** — this becomes the test/training data.
7. **Prep for the in-person OCR/server discussion** the JD flagged — walk in with a recommended OCR tool and a clear ask for the Nvidia box.

**Tip — prove a vertical slice first:** take *one* tender + its bidders through the *entire* pipeline before scaling to all 3–5. Depth beats breadth at the start.

---

## 4. Broad implementation plan

### Phase 1 — manual pilot / MVP engine

1. **Ingest & organize** — folder per tender (above).
2. **Requirement schema** — convert each tender's eligibility into structured rules (do manually first, automate later):

```json
{
  "requirement_id": "R1",
  "requirement": "Bidder must have valid GST registration",
  "required_document": "GST certificate",
  "field_to_extract": "GSTIN",
  "validation": "format + checksum + API verification",
  "tier": 1,
  "decision_values": ["Compliant", "Non-compliant", "Needs manual review"]
}
```

3. **Extraction layer** — digital PDFs → PyMuPDF/pdfplumber; scanned → OCR. Detect document type, extract fields, output JSON with **confidence + page/location**:

```json
{
  "bidder_name": "ABC Enterprises",
  "documents": [
    {"document_type": "GST Certificate", "gstin": "22AAAAA0000A1Z5", "confidence": 0.91, "page": 2},
    {"document_type": "PAN Card", "pan": "AAAAA0000A", "confidence": 0.88, "page": 1}
  ]
}
```

4. **Validation layer (Tier 1):**

| Field | Validation |
|-------|------------|
| PAN | Format check (AAAAA9999A; 4th char = entity type) |
| GSTIN | Format + offline checksum (15th char, base-36) |
| GSTIN ↔ PAN | **Cross-check: GSTIN chars 3–12 must equal the PAN** |
| GSTIN | API verification (if access available) |
| Vendor name | Fuzzy-match across documents (spelling varies) |
| Certificate | Presence + type detection |
| Dates | Validity / expiry check |
| Turnover | Numeric extraction + threshold compare |

> For ID numbers, format+checksum is the real gate — not OCR confidence. One misread character invalidates a GSTIN/PAN, so validate, don't trust the read.

5. **Requirement matching → matrix:** `Requirement → required evidence → bidder document → extracted value → decision`, emitted as a vendor-wise table:

| Requirement | Evidence | Bidder A | Confidence | Source | Decision |
|-------------|----------|---------:|-----------:|--------|----------|
| GST registration | GST cert | Found | 91% | Pg 2 | Compliant |
| PAN | PAN card | Found | 88% | Pg 1 | Compliant |
| Technical experience | Work cert | Unclear | 62% | Pg 5 | Manual Review |
| Financial turnover | CA cert | Not found | — | — | Manual Review |

6. **Human-in-the-loop review** — the tool **assists, never auto-accepts/rejects**. For each row show: extracted value, source document, page, confidence, suggested decision, and a manual-override control. Keep a full audit trail (tool-decided vs human-confirmed) — procurement is audit- and litigation-sensitive.

### Phase 1.5 — eligibility reasoning (Tier 2)

LLM reads each Tier-2 requirement against the relevant extracted evidence and returns a suggested decision + cited evidence, always flagged for human confirmation. Your existing RAG / local-LLM setup fits here.

### Phase 2 — automation (gated on approval)

1. **Document collection** — Chrome extension / browser automation using the logged-in GeM session to pull tenders + bidder docs. **First confirm:** GeM terms of use, infosec sign-off, and whether an **official bulk-download/API channel** exists for authorized government users (prefer it over scraping).
2. **Backend APIs** — upload, OCR, field extraction, PAN/GST validation, matrix generation, results to dashboard/Excel.
3. **Server/OCR** — GPU OCR pipeline on the Nvidia box. Confirm GPU is actually needed for the volume; storage location; and who may access the (PII-bearing) data.

---

## 4A. Phase 1 MVP — acceptance criteria, safeguards & data governance

Treat Phase 1 as a **controlled MVP**, scoped to **one complete tender with ≥3 bidders, processed end-to-end** into an Excel compliance matrix (requirement-wise Compliant / Needs Review / Not Found, with confidence and evidence page/location). Tier-1 fields in scope: vendor name, PAN, GSTIN, document type, certificate presence.

### Ground-truth dataset (build alongside the pilot)
For the pilot tender, officials manually record the correct values per bidder — PAN, GSTIN, vendor name, presence of each required document, and the evidence page. Store it as a simple sheet next to the system output; accuracy is then a diff of system output vs ground truth. Keep it small (1 tender × 3 bidders × Tier-1 fields ≈ a few dozen cells) — enough to measure accuracy and surface failure cases.

### Measurable acceptance gate (make "MVP success" testable)
Qualitative goals need numbers. Pass conditions:

| Criterion | What it measures | MVP target |
|---|---|---|
| Coverage | Every bidder × every required field produces a decision (no silent skips) | 100% |
| **Auto-mark precision** | Of fields the system *auto-decided*, share matching ground truth | **~100% — no confident-but-wrong marks** |
| Field extraction accuracy | Exact-match on PAN / GSTIN / vendor name vs ground truth | Report it; anything below the confidence threshold routes to review, never auto-marked |
| Evidence localization | Each auto-marked field shows a correct page/location | 100% verifiable in seconds |
| Review routing | Every field the system got wrong was one it had flagged as Needs Review | 100% |

The **binding gate is the safety one**: the auto-decided subset must be essentially error-free against ground truth. Recall (how much the system was confident enough to auto-mark) can be modest for an MVP — a higher manual-review rate is acceptable; confident wrong answers are not.

### Conservative decision principle (sharpened)
The tool **assists scrutiny; it does not replace the competent authority.** Two error types matter:
- *Type A — a present/valid document marked "missing/non-compliant"* → wrongful disqualification of a valid bidder → the procurement/audit risk.
- *Type B — a missing/invalid document marked "present/compliant"* → an ineligible bidder clears first scrutiny → integrity risk.

The safe design handles **both** — not by biasing toward "present," but by controlling which verdicts the tool may finalize:
- Auto-mark **"Compliant / Present" only** on a high-confidence deterministic check (format + checksum + API, or unambiguous presence).
- **Never finalize "Missing / Non-compliant."** Render it as **"Needs Review — likely missing,"** always requiring human confirmation, because a wrongful-rejection call has the highest downstream cost.
- Everything low-confidence, unclear, or Tier-2 semantic → **Needs Review.**

This avoids false negatives without creating false positives.

### Data governance (built into the MVP, not bolted on later)
Bidder documents carry PAN, GSTIN, financial certificates and commercial information — governance is part of the MVP:
- **Storage:** documents and outputs only in approved/sovereign locations (on-prem / academy infrastructure), not personal drives or unapproved cloud.
- **Access:** restricted to named officials on the tender; least-privilege.
- **External API egress — flag explicitly:** a GST *verification* API call transmits the bidder's GSTIN to an external/government endpoint — a data-egress event needing prior approval. Until approved, run **offline format + checksum + GSTIN↔PAN validation only**, and leave live verification as a flagged step.
- **Audit log (append-only):** log every system decision and every human override. Minimum fields:

```text
timestamp, tender_id, bidder_id, requirement_id,
extracted_value, confidence, evidence_page,
system_decision, decision_basis (rule|checksum|api|ocr|llm),
reviewer_id, human_decision, override_flag, override_reason
```

A clean override trail — what the tool said vs what the official decided, and why — is what makes the system defensible in an audit.

---

## 5. Concrete recommendations

- **OCR tool:** decide off the scanned-vs-digital gate. Digital → no OCR (PyMuPDF/pdfplumber). Scanned → pilot **PaddleOCR** (tables/structure, GPU-friendly) or **Surya** (layout + Hindi/Indic); **Tesseract** as a fast baseline only.
- **Output format:** **Excel** for v1 (officials live in it, auditable, easy to share) backed by **JSON** as the machine layer; dashboard later.
- **Free validations to bake in from day one:** PAN format, GSTIN format + checksum, **GSTIN↔PAN cross-check**, certificate date validity, fuzzy vendor-name matching across docs.
- **PII / DPDP:** bidder PAN/GST is sensitive personal/commercial data — restrict storage and access, and log who sees what.

---

## 6. Open questions to confirm with the JD / team

1. **Scope of v1:** document *presence* only, or also *eligibility compliance* (Tier 2)? (Biggest scoping call.)
2. **Scanned or digital** bidder PDFs — or mixed?
3. **OCR tool** — confirm intended choice (transcript hints at "Surya OCR"; PaddleOCR is a strong alternative).
4. **GST verification** — official/third-party API available, or format-only for now?
5. **Output** — Excel checklist, JSON, dashboard, or PDF report for v1?
6. **Scale** — how many tenders/bidders for the pilot, and ongoing volume? (Decides whether the GPU box is needed for the MVP.)
7. **Phase 2 approval** — is browser scraping of GeM cleared by security/legal, or should we pursue an official channel?

---

## 7. Internal wording you can reuse

> We are building a first-level GeM bid-document scrutiny system. In Phase 1 we manually download selected tenders and bidder documents, organize them tender- and bidder-wise, extract text via OCR/PDF extraction, and identify key fields (PAN, GSTIN, vendor name, technical and financial experience certificates, turnover). Checks are split into deterministic presence/format checks (auto-decided) and semantic eligibility checks (LLM-assisted, flagged for review). The system outputs a vendor-wise compliance matrix with Yes/No/Needs-Review status, confidence, and evidence location; low-confidence cases route to manual verification with a full audit trail. Once validated, Phase 2 automates document collection from GeM (subject to security/legal approval) and runs OCR/validation on backend/GPU infrastructure.

---

## 8. Execution order

**First:** pick 3–5 tenders → download tender + bidder docs → organize folders → write one manual checklist → mark scanned/digital → give to technical team.
**Next:** JSON extraction from bidder docs → PAN/GST validation (incl. GSTIN↔PAN) → presence-based compliance matrix → manual-review flags → Excel output.
**Then:** Tier-2 eligibility reasoning (LLM) → dashboard + audit trail.
**Later:** automate collection (Chrome extension / official channel) → move OCR to the server.
