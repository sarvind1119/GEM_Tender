"""Normalized verification result schema and review-safe wording.

Every registry lookup (PAN / GSTIN / MCA), whether mock or live, is normalized
into a single ``VerificationResult`` record. This module is also the single
source of reviewer-facing wording: ``review_note_for`` guarantees that no
final-decision language ever appears in verification outputs. A registry
outcome is evidence for human review, never a decision.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import asdict, dataclass, field
from typing import Any

SERVICE_PAN = "pan"
SERVICE_GSTIN = "gstin"
SERVICE_MCA = "mca"
ALL_SERVICES = (SERVICE_PAN, SERVICE_GSTIN, SERVICE_MCA)

OUTCOME_VERIFIED = "verified"
OUTCOME_NOT_FOUND = "not_found"
OUTCOME_STATUS_FLAG = "status_flag"
OUTCOME_ERROR = "error"
OUTCOME_SKIPPED = "skipped"

NAME_MATCH_HIGH = "high"
NAME_MATCH_MEDIUM = "medium"
NAME_MATCH_LOW = "low"
NAME_MATCH_NOT_TESTED = "not_tested"

# Final-decision wording that must never appear in verification outputs.
_FORBIDDEN_FRAGMENTS = ("reject", "disqualif", "non-compliant", "accept")

PAN_STRICT_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
GSTIN_STRICT_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
CIN_STRICT_RE = re.compile(r"^[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}$")
LLPIN_STRICT_RE = re.compile(r"^[A-Z]{3}-?\d{4}$")

INPUT_PATTERNS = {
    SERVICE_PAN: PAN_STRICT_RE,
    SERVICE_GSTIN: GSTIN_STRICT_RE,
    SERVICE_MCA: CIN_STRICT_RE,
}


@dataclass
class VerificationResult:
    service: str
    input_value: str
    bidder_id: str
    bidder_name: str
    outcome: str
    registry_status: str = ""
    registered_name: str = ""
    trade_name: str = ""
    name_match_score: float = 0.0
    name_match_band: str = NAME_MATCH_NOT_TESTED
    extra: dict[str, Any] = field(default_factory=dict)
    provider: str = ""
    provider_ref: str = ""
    verified_at: str = ""
    review_note: str = ""
    raw_response_sha256: str = ""

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


def normalize_name(value: str) -> str:
    value = re.sub(r"[^a-z0-9 ]+", " ", value.casefold())
    # Common company suffixes add noise to similarity scoring.
    value = re.sub(
        r"\b(private|pvt|limited|ltd|llp|opc|co|company|enterprises|industries|india)\b",
        " ",
        value,
    )
    return re.sub(r"\s+", " ", value).strip()


def name_match(bidder_name: str, registered_name: str) -> tuple[float, str]:
    left = normalize_name(bidder_name)
    right = normalize_name(registered_name)
    if not left or not right:
        return 0.0, NAME_MATCH_NOT_TESTED
    score = round(difflib.SequenceMatcher(None, left, right).ratio(), 3)
    if score >= 0.85:
        return score, NAME_MATCH_HIGH
    if score >= 0.6:
        return score, NAME_MATCH_MEDIUM
    return score, NAME_MATCH_LOW


def review_note_for(result: VerificationResult) -> str:
    service_label = {
        SERVICE_PAN: "PAN registry",
        SERVICE_GSTIN: "GSTN registry",
        SERVICE_MCA: "MCA registry",
    }.get(result.service, "Registry")
    if result.outcome == OUTCOME_VERIFIED:
        note = f"{service_label} record found; status '{result.registry_status}'."
        if result.name_match_band == NAME_MATCH_HIGH:
            note += " Registered name closely matches bidder name."
        elif result.name_match_band in (NAME_MATCH_MEDIUM, NAME_MATCH_LOW):
            note += (
                f" Registered name similarity is {result.name_match_band}"
                f" ({result.name_match_score}); please compare names during human review."
            )
    elif result.outcome == OUTCOME_STATUS_FLAG:
        note = (
            f"{service_label} reports status '{result.registry_status}';"
            " flagged for human review."
        )
    elif result.outcome == OUTCOME_NOT_FOUND:
        note = (
            f"{service_label} did not return a record for this value;"
            " needs human review (value may be misread or the registry may be incomplete)."
        )
    elif result.outcome == OUTCOME_ERROR:
        note = (
            f"{service_label} lookup could not be completed (technical error);"
            " this is not a finding about the bidder. Retry or review manually."
        )
    else:
        note = f"{service_label} lookup was skipped; no usable input value."
    assert_review_safe(note)
    return note


def assert_review_safe(text: str) -> None:
    lowered = text.casefold()
    for fragment in _FORBIDDEN_FRAGMENTS:
        if fragment in lowered:
            raise ValueError(f"Review-unsafe wording generated: contains '{fragment}'")
