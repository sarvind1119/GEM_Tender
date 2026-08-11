from __future__ import annotations

import json
from pathlib import Path

from tools.build_bidder_review_matrix import requirement_column_label
from ui.adapter import load_review_items, requirement_fingerprint


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def build_artifact_fixture(root: Path) -> None:
    output = root / "05_Extraction_Output"
    requirements = []
    for index in range(1, 39):
        requirement_type = "document" if index <= 7 else "condition"
        text = f"Requirement text {index}"
        if index == 7:
            text = "Requirement text 6"
        if index == 8:
            text = "Requirement text 6"
        requirements.append(
            {
                "requirement_id": f"REQ-TEST-{index:03d}",
                "requirement_type": requirement_type,
                "requirement_text": text,
                "normalized_item_text": text,
                "requirement_category": "experience" if index <= 5 else "other_condition",
                "canonical_doc_type": "",
                "expected_bidder_doc_group": "",
                "presence_check_ready": "Yes" if index <= 5 else "No",
                "needs_clause_expansion": "No" if index <= 5 else "Yes",
                "human_review_required_for_presence": "No" if index <= 5 else "Yes",
                "matching_keywords": "experience completion certificate" if index == 1 else text,
                "source_file": "tender.pdf",
                "source_page": 1,
                "source_snippet": f"Tender source for {text}",
            }
        )
    manifest = []
    identities = []
    pages = []
    matrices = []
    for bidder_index in range(1, 4):
        bidder_id = f"Bidder_{bidder_index:02d}"
        folder = f"03_Bidder_Submissions/{bidder_id}_Vendor_{bidder_index}"
        document_id = f"DOC-{bidder_index:04d}"
        file_name = f"experience_{bidder_index}.pdf"
        (root / folder).mkdir(parents=True, exist_ok=True)
        (root / folder / file_name).write_bytes(b"%PDF-1.4 synthetic")
        manifest.append(
            {
                "bidder_id": bidder_id,
                "bidder_name": f"V{bidder_index}",
                "document_id": document_id,
                "document_side": "bidder-side",
                "document_type_guess": "Experience certificate",
                "file_name": file_name,
                "folder_path": folder,
                "file_sha256": f"sha-{bidder_index}",
                "page_count": 2,
            }
        )
        identities.append(
            {
                "bidder_id": bidder_id,
                "bidder_name": f"V{bidder_index}",
                "pan": f"ABCDE{bidder_index:04d}F",
                "pan_status": "Extracted / Validated",
                "pan_source_file": file_name,
                "pan_page": 1,
                "gstin": "",
                "gstin_status": "Needs Review",
                "gstin_source_file": "",
                "gstin_page": "",
                "gstin_pan_match_status": "",
            }
        )
        pages.append(
            {
                "document_id": document_id,
                "file_name": file_name,
                "page_number": 2,
                "chosen_text": "Experience completion certificate for prior supplies.",
            }
        )
        matrix = {
            "tender_id": "Tender_Test",
            "bidder_id": bidder_id,
            "bidder_name": f"V{bidder_index}",
            "pan": "",
            "pan_status": "",
            "pan_source_file": "",
            "pan_page": "",
            "gstin": "",
            "gstin_status": "",
            "gstin_source_file": "",
            "gstin_page": "",
            "gstin_pan_match_status": "",
            "identity_needs_human_review": "Yes",
        }
        for requirement in requirements:
            label = requirement_column_label(requirement)
            present = requirement["requirement_id"] == "REQ-TEST-001"
            matrix[f"{label}_status"] = "Present" if present else "Needs Review"
            matrix[f"{label}_source_files"] = file_name if present else ""
            matrix[f"{label}_document_ids"] = document_id if present else ""
            matrix[f"{label}_review_notes"] = "Candidate found." if present else "Manual review."
        matrix.update(
            {
                "reviewer_decision": "",
                "reviewer_notes": "",
                "overall_needs_human_review": "Yes",
            }
        )
        assert len(matrix) == 168
        matrices.append(matrix)

    write_json(output / "document_manifest.json", manifest)
    write_json(output / "02_identity_extraction" / "bidder_identity_summary.json", identities)
    write_json(output / "05_tender_requirements" / "required_document_attributes.json", requirements)
    write_json(output / "06_bidder_review_matrix" / "bidder_document_review_matrix.json", matrices)
    write_json(output / "01_text_extraction" / "page_json" / "all_pages.json", pages)


def test_adapter_normalizes_168_column_matrix_and_preserves_type_context(tmp_path: Path) -> None:
    build_artifact_fixture(tmp_path)
    items = load_review_items(tmp_path)
    requirement_items = [item for item in items if item.renderer in {"document_presence", "manual_condition"}]

    # One exact same-type duplicate is merged. Identical text with a different
    # requirement type remains separate.
    assert len(requirement_items) == 37 * 3
    bidder_1 = [item for item in requirement_items if item.bidder_id == "Bidder_01"]
    same_text = [item for item in bidder_1 if item.requirement_text == "Requirement text 6"]
    assert len(same_text) == 2
    merged = next(item for item in same_text if item.requirement_type == "document")
    assert merged.contributing_requirement_ids == ("REQ-TEST-006", "REQ-TEST-007")

    first = next(item for item in bidder_1 if item.requirement_text == "Requirement text 1")
    assert first.evidence is not None
    assert first.evidence.authority == "suggested_page"
    assert first.evidence.page_number == 2
    assert first.evidence.match_score >= 2
    assert first.bidder_label == "Vendor 1"


def test_fingerprint_is_stable_when_positional_id_changes() -> None:
    first = requirement_fingerprint("financial_criteria", "Minimum annual turnover")
    second = requirement_fingerprint("financial_criteria", "Minimum annual turnover")
    different_type = requirement_fingerprint("oem_condition", "Minimum annual turnover")
    assert first == second
    assert first != different_type


def test_missing_candidate_document_is_explicitly_unavailable(tmp_path: Path) -> None:
    build_artifact_fixture(tmp_path)
    target = tmp_path / "03_Bidder_Submissions" / "Bidder_01_Vendor_1" / "experience_1.pdf"
    target.unlink()
    items = load_review_items(tmp_path)
    first = next(
        item
        for item in items
        if item.bidder_id == "Bidder_01" and item.requirement_text == "Requirement text 1"
    )
    # Page matching still identifies the intended page text, but the viewer must
    # downgrade it when resolving the physical file.
    assert first.evidence is not None
    assert first.evidence.authority == "unavailable"
    assert first.evidence.page_number is None


def test_utf8_round_trip_preserves_em_dash_and_indian_text(tmp_path: Path) -> None:
    value = {"status": "Needs Review — derived from GSTIN", "label": "निविदा समीक्षा"}
    path = tmp_path / "utf8.json"
    write_json(path, value)
    assert json.loads(path.read_text(encoding="utf-8")) == value
