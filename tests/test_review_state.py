from __future__ import annotations

from pathlib import Path

import pytest

from ui.adapter import ReviewItem, requirement_fingerprint
from ui.review_state import (
    audit_path,
    complete_bidder,
    completion_issues,
    load_state,
    reopen_bidder,
    review_conflicts,
    save_item_draft,
    set_manual_routing,
    set_reviewer,
)


def make_item(*, assessable: bool = True, text: str = "Experience certificate") -> ReviewItem:
    requirement_type = "document" if assessable else "condition"
    return ReviewItem(
        bidder_id="Bidder_01",
        bidder_label="Vendor One",
        requirement_fingerprint=requirement_fingerprint(requirement_type, text),
        contributing_requirement_ids=("REQ-001",),
        requirement_type=requirement_type,
        requirement_text=text,
        renderer="document_presence" if assessable else "manual_condition",
        system_status="Present" if assessable else "Not assessed",
        system_note="",
        assessable=assessable,
    )


def test_draft_completion_and_reopen_append_activity(tmp_path: Path) -> None:
    assessable = make_item()
    manual = make_item(assessable=False, text="ATC clause")
    items = [assessable, manual]

    set_reviewer(tmp_path, "Reviewer Name", "Procurement Officer")
    save_item_draft(
        tmp_path,
        assessable,
        outcome="Confirmed system finding",
        notes="",
    )
    set_manual_routing(
        tmp_path,
        "Bidder_01",
        acknowledged=True,
        note="Routed to the manual ATC review sheet.",
    )

    state = load_state(tmp_path)
    assert completion_issues(items, state, "Bidder_01") == []
    completed = complete_bidder(tmp_path, items, "Bidder_01")
    assert completed["bidder_reviews"]["Bidder_01"]["status"] == "completed"
    # Item submission, manual routing, and bidder completion are separate events.
    assert audit_path(tmp_path).read_text(encoding="utf-8").count("\n") == 3

    with pytest.raises(ValueError):
        reopen_bidder(tmp_path, "Bidder_01", "")
    reopened = reopen_bidder(tmp_path, "Bidder_01", "New bidder document supplied.")
    assert reopened["bidder_reviews"]["Bidder_01"]["status"] == "in_progress"
    assert audit_path(tmp_path).read_text(encoding="utf-8").count("\n") == 4


def test_manual_evidence_requires_document_and_note_at_completion(tmp_path: Path) -> None:
    item = make_item()
    set_reviewer(tmp_path, "Reviewer Name", "Officer")
    save_item_draft(
        tmp_path,
        item,
        outcome="Evidence located manually",
        notes="",
    )
    issues = completion_issues([item], load_state(tmp_path), "Bidder_01")
    assert any("Add a reviewer note" in issue for issue in issues)


def test_changed_fingerprint_surfaces_conflict(tmp_path: Path) -> None:
    old_item = make_item(text="Old wording")
    new_item = make_item(text="Updated wording")
    save_item_draft(
        tmp_path,
        old_item,
        outcome="Confirmed system finding",
        notes="",
    )
    conflicts = review_conflicts([new_item], load_state(tmp_path))
    assert len(conflicts["orphaned_decisions"]) == 1
    assert len(conflicts["new_items"]) == 1
