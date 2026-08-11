"""CIN candidate extraction from already-generated page-text outputs.

Deliberately reads Agent 1's existing ``all_pages.json`` instead of adding a
new pattern inside ``run_phase1_identity_extraction.py`` — no pipeline change
is required and no PDFs are re-parsed. Candidates carry source file, page,
and an evidence snippet, mirroring the PAN/GSTIN candidate conventions.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# CIN with optional OCR-introduced separators between characters, mirroring
# the tolerant PAN/GSTIN patterns used by Agent 1.
CIN_RE = re.compile(
    r"(?<![A-Z0-9])([LU](?:[\s\-.]*[0-9]){5}(?:[\s\-.]*[A-Z]){2}(?:[\s\-.]*[0-9]){4}"
    r"(?:[\s\-.]*[A-Z]){3}(?:[\s\-.]*[0-9]){6})(?![A-Z0-9])"
)


def normalize_cin(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _snippet(text: str, start: int, end: int, width: int = 80) -> str:
    left = max(start - width, 0)
    right = min(end + width, len(text))
    return re.sub(r"\s+", " ", text[left:right]).strip()


def extract_cin_candidates(tender_root: Path) -> list[dict[str, Any]]:
    """Scan bidder-side pages for CIN candidates.

    Returns one row per distinct (bidder, CIN, document, page) with evidence.
    """
    output_root = tender_root / "05_Extraction_Output"
    all_pages_path = output_root / "01_text_extraction" / "page_json" / "all_pages.json"
    manifest_path = output_root / "document_manifest.json"
    if not all_pages_path.exists() or not manifest_path.exists():
        return []
    try:
        pages = json.loads(all_pages_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    docs_by_id = {row.get("document_id", ""): row for row in manifest}
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, Any]] = set()
    for page in pages:
        doc = docs_by_id.get(page.get("document_id", ""), {})
        if doc.get("document_side") != "bidder-side":
            continue
        text = (page.get("chosen_text") or "").upper()
        for match in CIN_RE.finditer(text):
            normalized = normalize_cin(match.group(1))
            key = (doc.get("bidder_id", ""), normalized, page.get("document_id", ""), page.get("page_number"))
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "bidder_id": doc.get("bidder_id", ""),
                    "bidder_name": doc.get("bidder_name", ""),
                    "cin": normalized,
                    "source_file": doc.get("file_name", page.get("file_name", "")),
                    "source_page": page.get("page_number", ""),
                    "evidence_text_snippet": _snippet(text, match.start(1), match.end(1)),
                    "source_method": page.get("chosen_text_source", ""),
                }
            )
    return candidates


def cin_candidates_by_bidder(tender_root: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in extract_cin_candidates(tender_root):
        grouped.setdefault(row["bidder_id"], []).append(row)
    return grouped


def unique_cin_for_bidder(candidates: list[dict[str, Any]]) -> str:
    """Return the CIN only when the documents agree on exactly one value."""
    distinct = sorted({row["cin"] for row in candidates})
    return distinct[0] if len(distinct) == 1 else ""
