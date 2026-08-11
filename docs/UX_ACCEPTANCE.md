# Reviewer-First UI Acceptance

## Visual thesis

A calm, government-neutral scrutiny workspace: navy information hierarchy, restrained teal actions, compact typography, and status meaning carried by text and icons as well as colour.

## Content plan

1. Tender setup and processing status.
2. Tender requirement confirmation.
3. Bidder queue, review checklist, and evidence.
4. Normalized export and local review activity.

## Interaction thesis

- Selecting a bidder or finding changes the working context without exposing raw matrices.
- Checklist decisions rerun only their Streamlit fragment; cached PDF pages remain stable.
- Completing or reopening a bidder creates explicit local activity events.

## Baseline protocol

The current legacy UI remains available through:

```powershell
.\run_app.ps1 -Legacy
```

Before the first pilot, have the same official review the same completed tender once in the legacy UI and once in the reviewer-first UI. Record active minutes per bidder, excluding OCR time and breaks.

The reviewer-first UI passes when:

- median active review time per bidder is at least 30% lower;
- the primary review workflow has no horizontal page scrolling at 1366×768;
- every displayed evidence reference is labelled authoritative, suggested, manual, candidate-only, or unavailable;
- rerunning pipeline artifacts never silently remaps a stored decision;
- all manual-review conditions remain individually visible in the export.

Reviewer identity is self-declared. The local JSONL activity file is not authentication-backed or tamper-evident.

