from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from tools.pipeline_runner import write_json_atomic
from ui.adapter import ReviewItem, artifact_fingerprint, requirement_fingerprint


SCHEMA_VERSION = 1
OUTCOMES = (
    "",
    "Confirmed system finding",
    "Evidence located manually",
    "No evidence located after manual review",
    "Needs clarification",
    "Incorrect extraction or mapping",
    "Not applicable",
)
NOTE_REQUIRED_OUTCOMES = {
    "Evidence located manually",
    "No evidence located after manual review",
    "Needs clarification",
    "Incorrect extraction or mapping",
    "Not applicable",
}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def draft_path(tender_root: str | Path) -> Path:
    return Path(tender_root) / "review_draft.json"


def audit_path(tender_root: str | Path) -> Path:
    return Path(tender_root) / "review_audit.jsonl"


def _empty_state(tender_root: str | Path) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_fingerprint": artifact_fingerprint(tender_root),
        "reviewer": {"name": "", "designation": ""},
        "bidder_aliases": {},
        "items": {},
        "manual_routing": {},
        "bidder_reviews": {},
        "updated_at": now_iso(),
    }


def load_state(tender_root: str | Path) -> dict[str, Any]:
    path = draft_path(tender_root)
    if not path.exists():
        return _empty_state(tender_root)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        state = _empty_state(tender_root)
    default = _empty_state(tender_root)
    for key, value in default.items():
        state.setdefault(key, value)
    return state


def save_state(tender_root: str | Path, state: dict[str, Any]) -> None:
    state["schema_version"] = SCHEMA_VERSION
    state["updated_at"] = now_iso()
    write_json_atomic(draft_path(tender_root), state)


def item_key(bidder_id: str, fingerprint: str) -> str:
    return f"{bidder_id}\x1f{fingerprint}"


def append_activity(tender_root: str | Path, event: dict[str, Any]) -> None:
    path = audit_path(tender_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": now_iso(), **event}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def set_reviewer(tender_root: str | Path, name: str, designation: str) -> dict[str, Any]:
    state = load_state(tender_root)
    state["reviewer"] = {"name": name.strip(), "designation": designation.strip()}
    save_state(tender_root, state)
    return state


def set_bidder_alias(tender_root: str | Path, bidder_id: str, alias: str) -> dict[str, Any]:
    state = load_state(tender_root)
    if alias.strip():
        state["bidder_aliases"][bidder_id] = alias.strip()
    else:
        state["bidder_aliases"].pop(bidder_id, None)
    save_state(tender_root, state)
    return state


def save_item_draft(
    tender_root: str | Path,
    item: ReviewItem,
    *,
    outcome: str,
    notes: str,
    manual_document_id: str = "",
    manual_file_name: str = "",
    manual_page: int | None = None,
) -> dict[str, Any]:
    if outcome not in OUTCOMES:
        raise ValueError(f"Unsupported reviewer outcome: {outcome}")
    state = load_state(tender_root)
    key = item_key(item.bidder_id, item.requirement_fingerprint)
    existing = state["items"].get(key, {})
    state["items"][key] = {
        "bidder_id": item.bidder_id,
        "requirement_fingerprint": item.requirement_fingerprint,
        "contributing_requirement_ids": list(item.contributing_requirement_ids),
        "renderer": item.renderer,
        "requirement_text": item.requirement_text,
        "outcome": outcome,
        "notes": notes.strip(),
        "manual_source": {
            "document_id": manual_document_id.strip(),
            "file_name": manual_file_name.strip(),
            "page_number": manual_page,
        },
        "drafted_at": existing.get("drafted_at") or now_iso(),
        "updated_at": now_iso(),
        "submitted_at": existing.get("submitted_at", ""),
        "source_artifact_fingerprint": artifact_fingerprint(tender_root),
    }
    save_state(tender_root, state)
    return state["items"][key]


def validate_item_draft(draft: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    outcome = str(draft.get("outcome", ""))
    if not outcome:
        issues.append("Choose a reviewer outcome.")
    if outcome in NOTE_REQUIRED_OUTCOMES and not str(draft.get("notes", "")).strip():
        issues.append("Add a reviewer note for this outcome.")
    if outcome == "Evidence located manually":
        manual_source = draft.get("manual_source", {})
        if not str(manual_source.get("document_id", "")).strip():
            issues.append("Select the document where the evidence was located.")
    return issues


def set_manual_routing(
    tender_root: str | Path,
    bidder_id: str,
    *,
    acknowledged: bool,
    note: str,
) -> dict[str, Any]:
    state = load_state(tender_root)
    state["manual_routing"][bidder_id] = {
        "acknowledged": bool(acknowledged),
        "note": note.strip(),
        "updated_at": now_iso(),
    }
    save_state(tender_root, state)
    return state["manual_routing"][bidder_id]


def completion_issues(
    items: Iterable[ReviewItem],
    state: dict[str, Any],
    bidder_id: str,
) -> list[str]:
    items = list(items)
    issues: list[str] = []
    bidder_items = [item for item in items if item.bidder_id == bidder_id]
    for item in bidder_items:
        if not item.assessable:
            continue
        draft = state.get("items", {}).get(item_key(bidder_id, item.requirement_fingerprint), {})
        draft_issues = validate_item_draft(draft)
        if draft_issues:
            issues.append(f"{item.requirement_text}: {draft_issues[0]}")
    manual_items = [item for item in bidder_items if not item.assessable]
    if manual_items:
        routing = state.get("manual_routing", {}).get(bidder_id, {})
        if not routing.get("acknowledged") or not str(routing.get("note", "")).strip():
            issues.append("Acknowledge the manual-review conditions and add a routing note.")
    reviewer = state.get("reviewer", {})
    if not str(reviewer.get("name", "")).strip():
        issues.append("Enter the reviewer name before completing the bidder review.")
    return issues


def complete_bidder(
    tender_root: str | Path,
    items: Iterable[ReviewItem],
    bidder_id: str,
) -> dict[str, Any]:
    items = list(items)
    state = load_state(tender_root)
    issues = completion_issues(items, state, bidder_id)
    if issues:
        raise ValueError("\n".join(issues))
    submitted_at = now_iso()
    for item in items:
        if item.bidder_id != bidder_id or not item.assessable:
            continue
        key = item_key(bidder_id, item.requirement_fingerprint)
        state["items"][key]["submitted_at"] = submitted_at
    state["bidder_reviews"][bidder_id] = {
        "status": "completed",
        "completed_at": submitted_at,
        "reopened_at": "",
        "reopen_reason": "",
    }
    save_state(tender_root, state)
    for item in items:
        if item.bidder_id != bidder_id or not item.assessable:
            continue
        draft = state["items"][item_key(bidder_id, item.requirement_fingerprint)]
        source_references = []
        if item.evidence:
            source_references.append(item.evidence.to_dict())
        manual_source = draft.get("manual_source", {})
        if manual_source.get("document_id"):
            source_references.append({"authority": "manual_reference", **manual_source})
        append_activity(
            tender_root,
            {
                "event_type": "review_item_submitted",
                "triggered_by": "ui_button",
                "actor_claim": dict(state.get("reviewer", {})),
                "bidder_id": bidder_id,
                "requirement_fingerprint": item.requirement_fingerprint,
                "outcome": draft.get("outcome", ""),
                "reason": draft.get("notes", ""),
                "source_references": source_references,
            },
        )
    routing = state.get("manual_routing", {}).get(bidder_id, {})
    if routing.get("acknowledged"):
        append_activity(
            tender_root,
            {
                "event_type": "manual_review_routed",
                "triggered_by": "ui_button",
                "actor_claim": dict(state.get("reviewer", {})),
                "bidder_id": bidder_id,
                "requirement_fingerprint": "",
                "outcome": "routed_for_manual_review",
                "reason": routing.get("note", ""),
                "source_references": [],
            },
        )
    append_activity(
        tender_root,
        {
            "event_type": "bidder_review_completed",
            "triggered_by": "ui_button",
            "actor_claim": dict(state.get("reviewer", {})),
            "bidder_id": bidder_id,
            "requirement_fingerprint": "",
            "outcome": "completed",
            "reason": "",
            "source_references": [],
        },
    )
    return state


def reopen_bidder(tender_root: str | Path, bidder_id: str, reason: str) -> dict[str, Any]:
    if not reason.strip():
        raise ValueError("A reason is required to reopen a completed bidder review.")
    state = load_state(tender_root)
    review = state["bidder_reviews"].setdefault(bidder_id, {})
    review.update(
        {
            "status": "in_progress",
            "reopened_at": now_iso(),
            "reopen_reason": reason.strip(),
        }
    )
    save_state(tender_root, state)
    append_activity(
        tender_root,
        {
            "event_type": "bidder_review_reopened",
            "triggered_by": "ui_button",
            "actor_claim": dict(state.get("reviewer", {})),
            "bidder_id": bidder_id,
            "requirement_fingerprint": "",
            "outcome": "reopened",
            "reason": reason.strip(),
            "source_references": [],
        },
    )
    return state


def review_conflicts(items: Iterable[ReviewItem], state: dict[str, Any]) -> dict[str, list[str]]:
    current = {item_key(item.bidder_id, item.requirement_fingerprint) for item in items}
    stored = set(state.get("items", {}))
    return {
        "orphaned_decisions": sorted(stored - current),
        "new_items": sorted(current - stored),
    }


def import_legacy_turnover_reviews(
    tender_root: str | Path,
    items: Iterable[ReviewItem],
) -> int:
    state = load_state(tender_root)
    imported = 0
    for item in items:
        if item.renderer != "turnover":
            continue
        outcome = str(item.metadata.get("legacy_reviewer_decision", "")).strip()
        notes = str(item.metadata.get("legacy_reviewer_notes", "")).strip()
        key = item_key(item.bidder_id, item.requirement_fingerprint)
        if not outcome or key in state["items"]:
            continue
        mapped = outcome if outcome in OUTCOMES else "Needs clarification"
        state["items"][key] = {
            "bidder_id": item.bidder_id,
            "requirement_fingerprint": item.requirement_fingerprint,
            "contributing_requirement_ids": list(item.contributing_requirement_ids),
            "renderer": item.renderer,
            "requirement_text": item.requirement_text,
            "outcome": mapped,
            "notes": notes or f"Imported legacy outcome: {outcome}",
            "manual_source": {"document_id": "", "file_name": "", "page_number": None},
            "drafted_at": now_iso(),
            "updated_at": now_iso(),
            "submitted_at": "",
            "source_artifact_fingerprint": state.get("artifact_fingerprint", ""),
        }
        imported += 1
    if imported:
        save_state(tender_root, state)
    return imported


def export_rows(items: Iterable[ReviewItem], state: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    reviewer = state.get("reviewer", {})
    aliases = state.get("bidder_aliases", {})
    for item in items:
        draft = state.get("items", {}).get(item_key(item.bidder_id, item.requirement_fingerprint), {})
        evidence = item.evidence.to_dict() if item.evidence else {}
        manual_source = draft.get("manual_source", {})
        rows.append(
            {
                "bidder_id": item.bidder_id,
                "bidder_label": aliases.get(item.bidder_id) or item.bidder_label,
                "requirement_fingerprint": item.requirement_fingerprint,
                "contributing_requirement_ids": "; ".join(item.contributing_requirement_ids),
                "renderer": item.renderer,
                "requirement_type": item.requirement_type,
                "requirement_text": item.requirement_text,
                "assessable_by_system": "Yes" if item.assessable else "No",
                "system_status": item.system_status,
                "system_note": item.system_note,
                "evidence_authority": evidence.get("authority", "unavailable"),
                "source_file": evidence.get("file_name", ""),
                "source_page": evidence.get("page_number", ""),
                "source_snippet": evidence.get("snippet", ""),
                "reviewer_outcome": draft.get("outcome", ""),
                "reviewer_notes": draft.get("notes", ""),
                "manual_source_file": manual_source.get("file_name", ""),
                "manual_source_page": manual_source.get("page_number", ""),
                "reviewer_name_claim": reviewer.get("name", ""),
                "reviewer_designation_claim": reviewer.get("designation", ""),
                "drafted_at": draft.get("drafted_at", ""),
                "submitted_at": draft.get("submitted_at", ""),
            }
        )
    return rows
