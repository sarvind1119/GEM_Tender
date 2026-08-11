from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from tools.build_bidder_review_matrix import requirement_column_label


OUTPUT_DIR = "05_Extraction_Output"
GENERIC_MATCH_TERMS = {
    "and",
    "bid",
    "bidder",
    "certificate",
    "document",
    "evidence",
    "for",
    "from",
    "proof",
    "required",
    "the",
    "with",
}


@dataclass(frozen=True)
class EvidenceRef:
    authority: str
    document_id: str = ""
    file_name: str = ""
    folder_path: str = ""
    file_sha256: str = ""
    page_number: int | None = None
    snippet: str = ""
    matching_terms: tuple[str, ...] = ()
    match_score: float = 0.0
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewItem:
    bidder_id: str
    bidder_label: str
    requirement_fingerprint: str
    contributing_requirement_ids: tuple[str, ...]
    requirement_type: str
    requirement_text: str
    renderer: str
    system_status: str
    system_note: str
    assessable: bool
    tender_sources: tuple[dict[str, Any], ...] = ()
    candidate_documents: tuple[dict[str, Any], ...] = ()
    evidence: EvidenceRef | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.evidence is not None:
            value["evidence"] = self.evidence.to_dict()
        return value


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_page(value: Any) -> int | None:
    try:
        page = int(value)
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def _split_values(value: Any) -> list[str]:
    return [item.strip() for item in _as_text(value).split(";") if item.strip()]


def requirement_fingerprint(requirement_type: str, normalized_item_text: str) -> str:
    canonical = f"{requirement_type.strip().casefold()}\x1f{normalized_item_text.strip().casefold()}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def artifact_fingerprint(tender_root: str | Path) -> str:
    tender_root = Path(tender_root)
    output = tender_root / OUTPUT_DIR
    candidates = (
        output / "05_tender_requirements" / "required_document_attributes.json",
        output / "06_bidder_review_matrix" / "bidder_document_review_matrix.json",
        output / "02_identity_extraction" / "bidder_identity_summary.json",
        output / "07_turnover_evaluation" / "turnover_review_matrix.json",
        output / "08_verification" / "verification_matrix.json",
    )
    digest = hashlib.sha256()
    found = False
    for path in candidates:
        if not path.exists():
            continue
        found = True
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest() if found else ""


def _document_path(tender_root: Path, document: dict[str, Any]) -> Path:
    return tender_root / _as_text(document.get("folder_path")) / _as_text(document.get("file_name"))


def _document_summary(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_id": _as_text(document.get("document_id")),
        "file_name": _as_text(document.get("file_name")),
        "folder_path": _as_text(document.get("folder_path")),
        "file_sha256": _as_text(document.get("file_sha256")),
        "page_count": document.get("page_count") or 0,
        "document_type_guess": _as_text(document.get("document_type_guess")),
    }


def bidder_documents(tender_root: str | Path, bidder_id: str) -> list[dict[str, Any]]:
    tender_root = Path(tender_root)
    manifest = _load_json(tender_root / OUTPUT_DIR / "document_manifest.json", [])
    return [
        _document_summary(row)
        for row in manifest
        if _as_text(row.get("bidder_id")) == bidder_id and _as_text(row.get("document_side")) == "bidder-side"
    ]


def _folder_label(manifest: Iterable[dict[str, Any]], bidder_id: str) -> str:
    for row in manifest:
        if _as_text(row.get("bidder_id")) != bidder_id:
            continue
        folder = Path(_as_text(row.get("folder_path"))).name
        prefix = f"{bidder_id}_"
        if folder.startswith(prefix) and len(folder) > len(prefix):
            return folder[len(prefix) :].replace("_", " ").strip()
    return ""


def _bidder_labels(
    manifest: list[dict[str, Any]],
    identity_rows: list[dict[str, Any]],
    matrix_rows: list[dict[str, Any]],
) -> dict[str, str]:
    identity_by_bidder = {_as_text(row.get("bidder_id")): row for row in identity_rows}
    bidders = {
        _as_text(row.get("bidder_id"))
        for row in [*manifest, *identity_rows, *matrix_rows]
        if _as_text(row.get("bidder_id"))
    }
    labels: dict[str, str] = {}
    for bidder_id in sorted(bidders):
        folder = _folder_label(manifest, bidder_id)
        extracted = _as_text(identity_by_bidder.get(bidder_id, {}).get("bidder_name"))
        labels[bidder_id] = folder or extracted or bidder_id
    return labels


def _manifest_indexes(manifest: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id = {_as_text(row.get("document_id")): row for row in manifest if _as_text(row.get("document_id"))}
    by_bidder_file = {
        f"{_as_text(row.get('bidder_id'))}\x1f{_as_text(row.get('file_name')).casefold()}": row
        for row in manifest
        if _as_text(row.get("file_name"))
    }
    return by_id, by_bidder_file


def _keywords(value: Any) -> list[str]:
    terms = re.findall(r"[a-z0-9]{3,}", _as_text(value).casefold())
    return list(dict.fromkeys(term for term in terms if term not in GENERIC_MATCH_TERMS))


def _snippet(text: str, terms: list[str], radius: int = 220) -> str:
    lowered = text.casefold()
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    if not positions:
        return re.sub(r"\s+", " ", text).strip()[: radius * 2]
    start = max(0, min(positions) - radius)
    end = min(len(text), start + radius * 2)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def _candidate_documents(
    bidder_id: str,
    document_ids: list[str],
    source_files: list[str],
    by_id: dict[str, dict[str, Any]],
    by_bidder_file: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for document_id in document_ids:
        document = by_id.get(document_id)
        if document and document_id not in seen:
            candidates.append(document)
            seen.add(document_id)
    for file_name in source_files:
        document = by_bidder_file.get(f"{bidder_id}\x1f{file_name.casefold()}")
        if not document:
            continue
        document_id = _as_text(document.get("document_id"))
        if document_id not in seen:
            candidates.append(document)
            seen.add(document_id)
    return candidates


def resolve_evidence(
    tender_root: str | Path,
    candidate_documents: list[dict[str, Any]],
    page_rows: list[dict[str, Any]],
    matching_keywords: Any,
) -> EvidenceRef | None:
    tender_root = Path(tender_root)
    if not candidate_documents:
        return None
    terms = _keywords(matching_keywords)
    best: tuple[float, dict[str, Any], dict[str, Any], tuple[str, ...]] | None = None
    for document in candidate_documents:
        document_id = _as_text(document.get("document_id"))
        for page in page_rows:
            if _as_text(page.get("document_id")) != document_id:
                continue
            text = _as_text(page.get("chosen_text"))
            lowered = text.casefold()
            matched = tuple(term for term in terms if term in lowered)
            score = float(len(matched))
            if terms and len(matched) == len(terms):
                score += 1.0
            if best is None or score > best[0]:
                best = (score, document, page, matched)
    if best and best[0] >= 2:
        score, document, page, matched = best
        path = _document_path(tender_root, document)
        return EvidenceRef(
            authority="suggested_page" if path.exists() else "unavailable",
            document_id=_as_text(document.get("document_id")),
            file_name=_as_text(document.get("file_name")),
            folder_path=_as_text(document.get("folder_path")),
            file_sha256=_as_text(document.get("file_sha256")),
            page_number=_as_page(page.get("page_number")) if path.exists() else None,
            snippet=_snippet(_as_text(page.get("chosen_text")), list(matched)),
            matching_terms=matched,
            match_score=score,
            note=(
                "Suggested page based on keyword overlap; this is not an extracted citation."
                if path.exists()
                else "Page text matched, but the referenced candidate document is unavailable."
            ),
        )
    document = candidate_documents[0]
    path = _document_path(tender_root, document)
    return EvidenceRef(
        authority="document_candidate" if path.exists() else "unavailable",
        document_id=_as_text(document.get("document_id")),
        file_name=_as_text(document.get("file_name")),
        folder_path=_as_text(document.get("folder_path")),
        file_sha256=_as_text(document.get("file_sha256")),
        page_number=1 if path.exists() else None,
        note=(
            "Candidate document found, but no defensible page match was identified."
            if path.exists()
            else "The referenced candidate document is unavailable."
        ),
    )


def _authoritative_evidence(
    tender_root: Path,
    manifest: list[dict[str, Any]],
    bidder_id: str,
    file_name: Any,
    page: Any,
    snippet: Any = "",
) -> EvidenceRef | None:
    file_name = _as_text(file_name)
    if not file_name:
        return None
    document = next(
        (
            row
            for row in manifest
            if _as_text(row.get("bidder_id")) == bidder_id
            and _as_text(row.get("file_name")).casefold() == file_name.casefold()
        ),
        {},
    )
    path = _document_path(tender_root, document) if document else Path()
    return EvidenceRef(
        authority="authoritative_citation" if document and path.exists() else "unavailable",
        document_id=_as_text(document.get("document_id")),
        file_name=file_name,
        folder_path=_as_text(document.get("folder_path")),
        file_sha256=_as_text(document.get("file_sha256")),
        page_number=_as_page(page),
        snippet=_as_text(snippet),
        note=(
            "Source page supplied by the extraction pipeline."
            if document and path.exists()
            else "The extraction output references a source that is unavailable."
        ),
    )


def _identity_items(
    tender_root: Path,
    manifest: list[dict[str, Any]],
    identity_rows: list[dict[str, Any]],
    labels: dict[str, str],
) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    fingerprint = requirement_fingerprint("identity", "PAN and GSTIN identity")
    for row in identity_rows:
        bidder_id = _as_text(row.get("bidder_id"))
        evidence = _authoritative_evidence(
            tender_root,
            manifest,
            bidder_id,
            row.get("gstin_source_file") or row.get("pan_source_file"),
            row.get("gstin_page") or row.get("pan_page"),
        )
        status = " | ".join(
            part
            for part in (
                f"PAN: {_as_text(row.get('pan_status'))}",
                f"GSTIN: {_as_text(row.get('gstin_status'))}",
                f"GSTIN/PAN: {_as_text(row.get('gstin_pan_match_status'))}",
            )
            if not part.endswith(": ")
        )
        items.append(
            ReviewItem(
                bidder_id=bidder_id,
                bidder_label=labels.get(bidder_id, bidder_id),
                requirement_fingerprint=fingerprint,
                contributing_requirement_ids=("IDENTITY",),
                requirement_type="identity",
                requirement_text="PAN and GSTIN identity",
                renderer="identity",
                system_status=status or "Identity output unavailable",
                system_note="Identity values are extracted aids and require reviewer confirmation.",
                assessable=True,
                candidate_documents=tuple(
                    _document_summary(row_)
                    for row_ in manifest
                    if _as_text(row_.get("bidder_id")) == bidder_id
                ),
                evidence=evidence,
                metadata={
                    "pan": _as_text(row.get("pan")),
                    "pan_status": _as_text(row.get("pan_status")),
                    "gstin": _as_text(row.get("gstin")),
                    "gstin_status": _as_text(row.get("gstin_status")),
                    "gstin_pan_match_status": _as_text(row.get("gstin_pan_match_status")),
                    "raw_bidder_name": _as_text(row.get("bidder_name")),
                },
            )
        )
    return items


def _registry_items(
    verification_rows: list[dict[str, Any]],
    labels: dict[str, str],
) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for row in verification_rows:
        bidder_id = _as_text(row.get("bidder_id"))
        service = _as_text(row.get("service")).upper() or "Registry"
        items.append(
            ReviewItem(
                bidder_id=bidder_id,
                bidder_label=labels.get(bidder_id, bidder_id),
                requirement_fingerprint=requirement_fingerprint("registry", service),
                contributing_requirement_ids=(f"REGISTRY-{service}",),
                requirement_type="registry",
                requirement_text=f"{service} registry verification",
                renderer="registry",
                system_status=_as_text(row.get("outcome")) or "Not run",
                system_note=_as_text(row.get("review_note")),
                assessable=True,
                evidence=None,
                metadata=dict(row),
            )
        )
    return items


def _turnover_items(
    tender_root: Path,
    manifest: list[dict[str, Any]],
    turnover_rows: list[dict[str, Any]],
    labels: dict[str, str],
) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    specifications = (
        ("bidder", "Bidder average annual turnover"),
        ("oem", "OEM average annual turnover"),
    )
    for row in turnover_rows:
        bidder_id = _as_text(row.get("bidder_id"))
        for prefix, title in specifications:
            evidence = _authoritative_evidence(
                tender_root,
                manifest,
                bidder_id,
                row.get(f"{prefix}_turnover_source_file"),
                row.get(f"{prefix}_turnover_source_page"),
                row.get(f"{prefix}_turnover_evidence_text"),
            )
            items.append(
                ReviewItem(
                    bidder_id=bidder_id,
                    bidder_label=labels.get(bidder_id, bidder_id),
                    requirement_fingerprint=requirement_fingerprint("turnover", title),
                    contributing_requirement_ids=(f"TURNOVER-{prefix.upper()}",),
                    requirement_type="turnover",
                    requirement_text=title,
                    renderer="turnover",
                    system_status=_as_text(row.get(f"{prefix}_turnover_status")) or "Not evaluated",
                    system_note="Numeric comparison is a conservative reviewer aid, not an eligibility decision.",
                    assessable=True,
                    candidate_documents=tuple(
                        _document_summary(row_)
                        for row_ in manifest
                        if _as_text(row_.get("bidder_id")) == bidder_id
                    ),
                    evidence=evidence,
                    metadata={
                        "threshold": row.get(f"{prefix}_turnover_threshold"),
                        "extracted_average": row.get(f"{prefix}_turnover_extracted_average"),
                        "llm_confidence": row.get("llm_confidence"),
                        "legacy_reviewer_decision": _as_text(row.get("reviewer_decision")),
                        "legacy_reviewer_notes": _as_text(row.get("reviewer_notes")),
                    },
                )
            )
    return items


def _requirement_groups(requirements: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for requirement in requirements:
        text = _as_text(requirement.get("normalized_item_text") or requirement.get("requirement_text"))
        fingerprint = requirement_fingerprint(_as_text(requirement.get("requirement_type")), text)
        if fingerprint not in groups:
            groups[fingerprint] = []
            order.append(fingerprint)
        groups[fingerprint].append(requirement)
    return [groups[key] for key in order]


def load_review_items(tender_root: str | Path) -> list[ReviewItem]:
    tender_root = Path(tender_root).resolve()
    output = tender_root / OUTPUT_DIR
    manifest = _load_json(output / "document_manifest.json", [])
    identity_rows = _load_json(output / "02_identity_extraction" / "bidder_identity_summary.json", [])
    requirements = _load_json(output / "05_tender_requirements" / "required_document_attributes.json", [])
    matrix_rows = _load_json(output / "06_bidder_review_matrix" / "bidder_document_review_matrix.json", [])
    turnover_rows = _load_json(output / "07_turnover_evaluation" / "turnover_review_matrix.json", [])
    verification_rows = _load_json(output / "08_verification" / "verification_matrix.json", [])
    page_rows = _load_json(output / "01_text_extraction" / "page_json" / "all_pages.json", [])

    labels = _bidder_labels(manifest, identity_rows, matrix_rows)
    by_id, by_bidder_file = _manifest_indexes(manifest)
    matrix_by_bidder = {_as_text(row.get("bidder_id")): row for row in matrix_rows}

    items: list[ReviewItem] = []
    items.extend(_identity_items(tender_root, manifest, identity_rows, labels))
    items.extend(_registry_items(verification_rows, labels))
    items.extend(_turnover_items(tender_root, manifest, turnover_rows, labels))

    for group in _requirement_groups(requirements):
        representative = group[0]
        normalized_text = _as_text(
            representative.get("normalized_item_text") or representative.get("requirement_text")
        )
        requirement_type = _as_text(representative.get("requirement_type")) or "requirement"
        fingerprint = requirement_fingerprint(requirement_type, normalized_text)
        requirement_ids = tuple(_as_text(row.get("requirement_id")) for row in group)
        tender_sources = tuple(
            {
                "requirement_id": _as_text(row.get("requirement_id")),
                "source_file": _as_text(row.get("source_file")),
                "source_page": _as_page(row.get("source_page")),
                "source_snippet": _as_text(row.get("source_snippet") or row.get("source_text_snippet")),
            }
            for row in group
        )
        assessable = all(
            _as_text(row.get("presence_check_ready")).casefold() == "yes"
            and _as_text(row.get("human_review_required_for_presence")).casefold() != "yes"
            for row in group
        )
        for bidder_id, label in labels.items():
            matrix = matrix_by_bidder.get(bidder_id, {})
            statuses: list[str] = []
            notes: list[str] = []
            document_ids: list[str] = []
            source_files: list[str] = []
            for requirement in group:
                column = requirement_column_label(requirement)
                statuses.append(_as_text(matrix.get(f"{column}_status")))
                notes.append(_as_text(matrix.get(f"{column}_review_notes")))
                document_ids.extend(_split_values(matrix.get(f"{column}_document_ids")))
                source_files.extend(_split_values(matrix.get(f"{column}_source_files")))
            candidates = _candidate_documents(
                bidder_id,
                list(dict.fromkeys(document_ids)),
                list(dict.fromkeys(source_files)),
                by_id,
                by_bidder_file,
            )
            evidence = resolve_evidence(
                tender_root,
                candidates,
                page_rows,
                representative.get("matching_keywords") or normalized_text,
            )
            items.append(
                ReviewItem(
                    bidder_id=bidder_id,
                    bidder_label=label,
                    requirement_fingerprint=fingerprint,
                    contributing_requirement_ids=requirement_ids,
                    requirement_type=requirement_type,
                    requirement_text=normalized_text,
                    renderer="document_presence" if assessable else "manual_condition",
                    system_status=" | ".join(dict.fromkeys(status for status in statuses if status))
                    or "Not assessed",
                    system_note=" | ".join(dict.fromkeys(note for note in notes if note)),
                    assessable=assessable,
                    tender_sources=tender_sources,
                    candidate_documents=tuple(_document_summary(row) for row in candidates),
                    evidence=evidence,
                    metadata={
                        "requirement_category": _as_text(representative.get("requirement_category")),
                        "expected_bidder_evidence": _as_text(representative.get("expected_bidder_evidence")),
                        "matching_keywords": _as_text(representative.get("matching_keywords")),
                        "needs_clause_expansion": any(
                            _as_text(row.get("needs_clause_expansion")).casefold() == "yes" for row in group
                        ),
                    },
                )
            )
    renderer_order = {
        "identity": 0,
        "registry": 1,
        "document_presence": 2,
        "turnover": 3,
        "manual_condition": 4,
    }
    return sorted(
        items,
        key=lambda item: (
            item.bidder_id,
            renderer_order.get(item.renderer, 99),
            item.requirement_text.casefold(),
        ),
    )


def review_items_by_bidder(items: Iterable[ReviewItem]) -> dict[str, list[ReviewItem]]:
    grouped: dict[str, list[ReviewItem]] = {}
    for item in items:
        grouped.setdefault(item.bidder_id, []).append(item)
    return grouped
