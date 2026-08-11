"""Provider-shaped mock responses for PAN / GSTIN / MCA lookups.

Shared by the in-process ``MockProvider`` and the local mock HTTP server so
both transports return identical answers. Responses imitate the shape of the
real providers (NSDL/Protean-style PAN, GSTN-style GSTIN, MCA master data)
so the response adapters in ``providers.py`` are exercised end-to-end even
in mock mode.

Determinism: unknown inputs are synthesized from ``sha256(value)`` so the
same input always yields the same answer across runs.

NOTE: seeds below are intentionally synthetic. Do not seed with real bidder
PAN/GSTIN values — fixture code is committed to Git and the project's data
policy keeps real identifiers out of the repository.
"""

from __future__ import annotations

import hashlib
from typing import Any

from tools.verification.schema import (
    CIN_STRICT_RE,
    GSTIN_STRICT_RE,
    PAN_STRICT_RE,
)

# Distribution for synthesized outcomes (percent thresholds over digest byte 0).
_P_VERIFIED = 80
_P_NOT_FOUND = 90
_P_FLAGGED = 97  # remainder (97-99) simulates a provider-side error

_GSTIN_FLAG_STATUSES = ("Cancelled", "Suspended")
_MCA_FLAG_STATUSES = ("Strike Off", "Under Process of Striking Off")

_SYNTH_NAME_WORDS = (
    "Astra", "Bharat", "Crystal", "Deccan", "Everest", "Falcon", "Ganga",
    "Himalay", "Indus", "Jyoti", "Kaveri", "Lotus", "Meridian", "Nova",
    "Orion", "Prakash",
)
_SYNTH_NAME_SUFFIXES = ("Industries", "Enterprises", "Traders", "Solutions", "Products")

# Hand-seeded records for demos/tests: every interesting case is reachable
# with a stable, obviously synthetic input value.
KNOWN_PAN: dict[str, dict[str, Any]] = {
    # Valid and active PAN.
    "ABCDE1234F": {"pan_status": "E", "name_on_card": "Demo Trading Company"},
    # PAN exists but is flagged inoperative in the registry.
    "ABCDE1234X": {"pan_status": "X", "name_on_card": "Demo Trading Company"},
    # Simulates record-not-found.
    "ZZZZZ9999Z": None,
}
KNOWN_GSTIN: dict[str, dict[str, Any]] = {
    "27ABCDE1234F1Z5": {
        "sts": "Active",
        "lgnm": "Demo Trading Company",
        "tradeNam": "Demo Traders",
        "rgdt": "01/07/2017",
    },
    "27ABCDE1234X1Z9": {
        "sts": "Cancelled",
        "lgnm": "Demo Trading Company",
        "tradeNam": "Demo Traders",
        "rgdt": "01/07/2017",
    },
    "09ZZZZZ9999Z1Z1": None,
}
KNOWN_CIN: dict[str, dict[str, Any]] = {
    "U12345MH2010PTC123456": {
        "companyName": "Demo Trading Company Private Limited",
        "companyStatus": "Active",
        "rocName": "RoC-Mumbai",
        "dateOfIncorporation": "2010-04-15",
    },
    "U54321DL2008PTC654321": {
        "companyName": "Demo Trading Company Private Limited",
        "companyStatus": "Strike Off",
        "rocName": "RoC-Delhi",
        "dateOfIncorporation": "2008-01-20",
    },
    "U99999KA1999PTC999999": None,
}
# Input values that always simulate a provider-side failure (any service).
ERROR_TRIGGER_VALUES = {"ABCDE1234E", "27ABCDE1234E1Z0", "U00000MH2000PTC000000"}


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def _synth_outcome(value: str) -> str:
    bucket = _digest(value)[0] % 100
    if bucket < _P_VERIFIED:
        return "verified"
    if bucket < _P_NOT_FOUND:
        return "not_found"
    if bucket < _P_FLAGGED:
        return "flagged"
    return "error"


def _synth_name(value: str, bidder_name_hint: str) -> str:
    digest = _digest(value)
    # Echo a lightly perturbed hint most of the time so realistic
    # name-match bands occur; otherwise fabricate a stable name.
    if bidder_name_hint and digest[1] % 100 < 70:
        return f"{bidder_name_hint.strip().title()} Private Limited"
    word = _SYNTH_NAME_WORDS[digest[2] % len(_SYNTH_NAME_WORDS)]
    suffix = _SYNTH_NAME_SUFFIXES[digest[3] % len(_SYNTH_NAME_SUFFIXES)]
    return f"{word} {suffix} Private Limited"


def _not_found(service: str, value: str) -> tuple[int, dict[str, Any]]:
    return 404, {"error_code": "RECORD_NOT_FOUND", "service": service, "query": value}


def _provider_error() -> tuple[int, dict[str, Any]]:
    return 500, {"error_code": "INTERNAL_ERROR", "message": "Simulated upstream failure."}


def pan_response(pan: str, bidder_name_hint: str = "") -> tuple[int, dict[str, Any]]:
    """NSDL/Protean-style PAN verification response as (http_status, body)."""
    pan = pan.strip().upper()
    if not PAN_STRICT_RE.match(pan):
        return 400, {"error_code": "INVALID_PAN_FORMAT", "pan": pan}
    if pan in ERROR_TRIGGER_VALUES:
        return _provider_error()
    if pan in KNOWN_PAN:
        seeded = KNOWN_PAN[pan]
        if seeded is None:
            return _not_found("pan", pan)
        return 200, {"pan": pan, "last_updated": "2026-04-01", **seeded}
    outcome = _synth_outcome(pan)
    if outcome == "not_found":
        return _not_found("pan", pan)
    if outcome == "error":
        return _provider_error()
    status = "E" if outcome == "verified" else "X"
    return 200, {
        "pan": pan,
        "pan_status": status,
        "name_on_card": _synth_name(pan, bidder_name_hint),
        "last_updated": "2026-04-01",
    }


def gstin_response(gstin: str, bidder_name_hint: str = "") -> tuple[int, dict[str, Any]]:
    """GSTN-style taxpayer detail response as (http_status, body)."""
    gstin = gstin.strip().upper()
    if not GSTIN_STRICT_RE.match(gstin):
        return 400, {"error_code": "INVALID_GSTIN_FORMAT", "gstin": gstin}
    if gstin in ERROR_TRIGGER_VALUES:
        return _provider_error()
    if gstin in KNOWN_GSTIN:
        seeded = KNOWN_GSTIN[gstin]
        if seeded is None:
            return _not_found("gstin", gstin)
        return 200, {"gstin": gstin, "stjCd": f"ST{gstin[:2]}", **seeded}
    outcome = _synth_outcome(gstin)
    if outcome == "not_found":
        return _not_found("gstin", gstin)
    if outcome == "error":
        return _provider_error()
    if outcome == "flagged":
        status = _GSTIN_FLAG_STATUSES[_digest(gstin)[4] % len(_GSTIN_FLAG_STATUSES)]
    else:
        status = "Active"
    name = _synth_name(gstin, bidder_name_hint)
    return 200, {
        "gstin": gstin,
        "sts": status,
        "lgnm": name,
        "tradeNam": name.replace(" Private Limited", ""),
        "rgdt": "01/07/2017",
        "stjCd": f"ST{gstin[:2]}",
    }


def mca_cin_response(cin: str, bidder_name_hint: str = "") -> tuple[int, dict[str, Any]]:
    """MCA master-data response as (http_status, body)."""
    cin = cin.strip().upper()
    if not CIN_STRICT_RE.match(cin):
        return 400, {"error_code": "INVALID_CIN_FORMAT", "cin": cin}
    if cin in ERROR_TRIGGER_VALUES:
        return _provider_error()
    if cin in KNOWN_CIN:
        seeded = KNOWN_CIN[cin]
        if seeded is None:
            return _not_found("mca", cin)
        return 200, {"cin": cin, **seeded}
    outcome = _synth_outcome(cin)
    if outcome == "not_found":
        return _not_found("mca", cin)
    if outcome == "error":
        return _provider_error()
    if outcome == "flagged":
        status = _MCA_FLAG_STATUSES[_digest(cin)[4] % len(_MCA_FLAG_STATUSES)]
    else:
        status = "Active"
    return 200, {
        "cin": cin,
        "companyName": _synth_name(cin, bidder_name_hint),
        "companyStatus": status,
        "rocName": f"RoC-{cin[6:8]}",
        "dateOfIncorporation": f"{cin[8:12]}-06-01",
    }


def mca_search_response(name: str) -> tuple[int, dict[str, Any]]:
    """MCA company name-search response as (http_status, body)."""
    name = name.strip()
    if not name:
        return 400, {"error_code": "EMPTY_QUERY"}
    digest = _digest(name.casefold())
    if digest[0] % 100 < 15:
        return 200, {"query": name, "results": []}
    # Deterministically fabricate a CIN whose lookup will succeed for demos.
    year = 2000 + digest[5] % 24
    serial = int.from_bytes(digest[6:9], "big") % 1000000
    cin = f"U{digest[9] % 10}{digest[10] % 10}345MH{year}PTC{serial:06d}"
    return 200, {
        "query": name,
        "results": [
            {
                "cin": cin,
                "companyName": f"{name.title()} Private Limited",
                "companyStatus": "Active",
                "rocName": "RoC-Mumbai",
            }
        ],
    }
