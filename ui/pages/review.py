from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any, Callable

import streamlit as st

from ui.adapter import (
    EvidenceRef,
    ReviewItem,
    artifact_fingerprint,
    bidder_documents,
    load_review_items,
    review_items_by_bidder,
)
from ui.pdf_renderer import RENDERER_NAME, render_pdf_page
from ui.review_state import (
    OUTCOMES,
    complete_bidder,
    completion_issues,
    import_legacy_turnover_reviews,
    item_key,
    load_state,
    reopen_bidder,
    review_conflicts,
    save_item_draft,
    set_bidder_alias,
    set_manual_routing,
    set_reviewer,
    validate_item_draft,
)


def _fragment(*args: Any, **kwargs: Any) -> Callable[..., Any]:
    decorator = getattr(st, "fragment", None) or getattr(st, "experimental_fragment", None)
    if decorator is not None:
        return decorator(*args, **kwargs)
    if args and callable(args[0]):
        return args[0]
    return lambda func: func


def _prefix(item: ReviewItem) -> str:
    return f"review_{item.bidder_id}_{item.requirement_fingerprint[:16]}"


def _manual_document(
    documents: list[dict[str, Any]],
    document_id: str,
) -> dict[str, Any]:
    return next((row for row in documents if row.get("document_id") == document_id), {})


def _save_widget_draft(tender_root: str, item: ReviewItem, documents: list[dict[str, Any]]) -> None:
    prefix = _prefix(item)
    document_id = str(st.session_state.get(f"{prefix}_manual_document", ""))
    document = _manual_document(documents, document_id)
    page_known = bool(st.session_state.get(f"{prefix}_manual_page_known", False))
    page_value = st.session_state.get(f"{prefix}_manual_page", 1) if page_known else None
    save_item_draft(
        tender_root,
        item,
        outcome=str(st.session_state.get(f"{prefix}_outcome", "")),
        notes=str(st.session_state.get(f"{prefix}_notes", "")),
        manual_document_id=document_id,
        manual_file_name=str(document.get("file_name", "")),
        manual_page=int(page_value) if page_value else None,
    )


def _initialize_widgets(
    item: ReviewItem,
    draft: dict[str, Any],
) -> None:
    prefix = _prefix(item)
    manual_source = draft.get("manual_source", {})
    defaults = {
        f"{prefix}_outcome": draft.get("outcome", ""),
        f"{prefix}_notes": draft.get("notes", ""),
        f"{prefix}_manual_document": manual_source.get("document_id", ""),
        f"{prefix}_manual_page_known": manual_source.get("page_number") not in {None, ""},
        f"{prefix}_manual_page": manual_source.get("page_number") or 1,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _render_item_metadata(item: ReviewItem) -> None:
    if item.renderer == "identity":
        left, right = st.columns(2)
        left.metric("PAN", item.metadata.get("pan") or "Not found")
        right.metric("GSTIN", item.metadata.get("gstin") or "Not found")
        st.caption(
            f"PAN: {item.metadata.get('pan_status') or '—'} · "
            f"GSTIN: {item.metadata.get('gstin_status') or '—'}"
        )
    elif item.renderer == "turnover":
        left, right = st.columns(2)
        left.metric("Threshold", item.metadata.get("threshold") or "Not found")
        average = item.metadata.get("extracted_average")
        right.metric("Extracted average", f"₹{average:,.0f}" if isinstance(average, (int, float)) else "Not found")
        confidence = item.metadata.get("llm_confidence")
        if confidence not in {None, ""}:
            st.caption(f"LLM/fallback confidence: {float(confidence):.2f}")
    elif item.renderer == "registry":
        metadata = item.metadata
        left, right = st.columns(2)
        left.metric("Registry outcome", metadata.get("outcome") or "Not run")
        right.metric("Name match", metadata.get("name_match_band") or "Not tested")
        if metadata.get("registered_name"):
            st.caption(f"Registered name: {metadata.get('registered_name')}")


@_fragment
def decision_editor(tender_root: str, item: ReviewItem, documents: list[dict[str, Any]]) -> None:
    state = load_state(tender_root)
    draft = state.get("items", {}).get(item_key(item.bidder_id, item.requirement_fingerprint), {})
    _initialize_widgets(item, draft)
    prefix = _prefix(item)

    st.markdown(
        f"""
        <div class="system-finding">
          <div class="label">System finding</div>
          <div class="value">{escape(item.system_status)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if item.system_note:
        st.caption(item.system_note)
    _render_item_metadata(item)

    st.selectbox(
        "Reviewer outcome",
        OUTCOMES,
        key=f"{prefix}_outcome",
        on_change=_save_widget_draft,
        args=(tender_root, item, documents),
        help="This reviews the system finding; it is not a bidder qualification decision.",
    )
    if st.session_state.get(f"{prefix}_outcome") == "Evidence located manually":
        options = [""] + [str(row.get("document_id", "")) for row in documents]
        labels = {
            "": "Select a bidder document",
            **{
                str(row.get("document_id", "")): str(row.get("file_name", ""))
                for row in documents
            },
        }
        st.selectbox(
            "Manual evidence document",
            options,
            format_func=lambda value: labels.get(value, value),
            key=f"{prefix}_manual_document",
            on_change=_save_widget_draft,
            args=(tender_root, item, documents),
        )
        st.checkbox(
            "Page number known",
            key=f"{prefix}_manual_page_known",
            on_change=_save_widget_draft,
            args=(tender_root, item, documents),
        )
        if st.session_state.get(f"{prefix}_manual_page_known"):
            document = _manual_document(
                documents,
                str(st.session_state.get(f"{prefix}_manual_document", "")),
            )
            page_count = max(1, int(document.get("page_count") or 1))
            st.number_input(
                "Manual evidence page",
                min_value=1,
                max_value=page_count,
                key=f"{prefix}_manual_page",
                on_change=_save_widget_draft,
                args=(tender_root, item, documents),
            )
    st.text_area(
        "Reviewer note",
        key=f"{prefix}_notes",
        height=100,
        on_change=_save_widget_draft,
        args=(tender_root, item, documents),
        help="Required for all outcomes except a straightforward confirmation.",
    )
    refreshed = load_state(tender_root)
    refreshed_draft = refreshed.get("items", {}).get(
        item_key(item.bidder_id, item.requirement_fingerprint),
        {},
    )
    issues = validate_item_draft(refreshed_draft)
    if refreshed_draft:
        if issues:
            st.caption("Draft saved locally · " + issues[0])
        else:
            st.success("Draft saved locally and ready for bidder completion.")


@st.cache_data(show_spinner=False)
def _cached_pdf_page(
    renderer: str,
    file_sha256: str,
    path: str,
    page_number: int,
    dpi: int,
) -> bytes:
    del renderer, file_sha256
    return render_pdf_page(path, page_number, dpi)


@st.cache_data(show_spinner=False)
def _cached_review_items(tender_root: str, source_fingerprint: str) -> list[ReviewItem]:
    del source_fingerprint
    return load_review_items(tender_root)


def _effective_evidence(
    item: ReviewItem,
    draft: dict[str, Any],
    documents: list[dict[str, Any]],
) -> EvidenceRef | None:
    manual_source = draft.get("manual_source", {})
    if draft.get("outcome") == "Evidence located manually" and manual_source.get("document_id"):
        document = _manual_document(documents, str(manual_source.get("document_id")))
        return EvidenceRef(
            authority="manual_reference",
            document_id=str(document.get("document_id", "")),
            file_name=str(document.get("file_name", "")),
            folder_path=str(document.get("folder_path", "")),
            file_sha256=str(document.get("file_sha256", "")),
            page_number=manual_source.get("page_number"),
            note="Source selected manually by the reviewer.",
        )
    return item.evidence


def _authority_label(authority: str) -> tuple[str, str]:
    labels = {
        "authoritative_citation": ("Authoritative pipeline citation", ""),
        "suggested_page": ("Suggested page — verify manually", "suggested"),
        "document_candidate": ("Candidate document — no page citation", "suggested"),
        "manual_reference": ("Reviewer-supplied reference", ""),
        "unavailable": ("Source unavailable", "unavailable"),
    }
    return labels.get(authority, ("Evidence unavailable", "unavailable"))


@_fragment
def evidence_viewer(tender_root: str, item: ReviewItem, documents: list[dict[str, Any]]) -> None:
    state = load_state(tender_root)
    draft = state.get("items", {}).get(item_key(item.bidder_id, item.requirement_fingerprint), {})
    evidence = _effective_evidence(item, draft, documents)
    st.markdown("**Evidence**")
    if evidence is None:
        label, css = _authority_label("unavailable")
        st.markdown(f"<span class='evidence-tag {css}'>{label}</span>", unsafe_allow_html=True)
        st.info("No bidder evidence was linked by the system.")
    else:
        label, css = _authority_label(evidence.authority)
        st.markdown(f"<span class='evidence-tag {css}'>{label}</span>", unsafe_allow_html=True)
        st.caption(evidence.note)
        if evidence.file_name:
            st.write(f"**{evidence.file_name}**")
        path = Path(tender_root) / evidence.folder_path / evidence.file_name
        if evidence.page_number and path.exists():
            try:
                image = _cached_pdf_page(
                    RENDERER_NAME,
                    evidence.file_sha256,
                    str(path),
                    int(evidence.page_number),
                    125,
                )
            except (FileNotFoundError, IndexError, RuntimeError, ValueError) as exc:
                st.warning(f"Source page unavailable: {exc}")
            else:
                st.image(image, caption=f"Page {evidence.page_number}", width="stretch")
        elif evidence.file_name:
            st.warning("Candidate document is known, but no page citation is available.")
        if evidence.snippet:
            st.text_area(
                "Extracted source text",
                evidence.snippet,
                disabled=True,
                height=155,
                key=f"evidence_snippet_{item.bidder_id}_{item.requirement_fingerprint[:16]}",
            )
        if evidence.matching_terms:
            st.caption("Matched terms: " + ", ".join(evidence.matching_terms))

    with st.expander("Tender-side provenance", expanded=False):
        if not item.tender_sources:
            st.caption("No tender-side source is attached to this item.")
        for source in item.tender_sources:
            st.write(
                f"`{source.get('requirement_id', '')}` · "
                f"{source.get('source_file') or 'Source unavailable'} · "
                f"page {source.get('source_page') or '—'}"
            )
            if source.get("source_snippet"):
                st.caption(str(source["source_snippet"]))

    if item.renderer == "registry":
        if st.button(
            "Refresh this registry check",
            key=f"refresh_registry_{item.bidder_id}_{item.requirement_fingerprint[:12]}",
            width="stretch",
        ):
            from tools.verification import engine as verification_engine

            service = str(item.metadata.get("service") or "").lower()
            with st.spinner("Running the configured registry provider…"):
                try:
                    verification_engine.run_verification(
                        Path(tender_root),
                        bidder_ids=[item.bidder_id],
                        services=(service,),
                        cin_map={},
                        triggered_by="review_workspace",
                        log=lambda message: None,
                    )
                except Exception as exc:  # noqa: BLE001 - surface provider failures
                    st.error(f"Registry verification failed: {exc}")
                else:
                    st.success("Registry verification refreshed. Reload the page to see the updated result.")


def _item_label(item: ReviewItem, state: dict[str, Any]) -> str:
    draft = state.get("items", {}).get(item_key(item.bidder_id, item.requirement_fingerprint), {})
    marker = "✓" if not validate_item_draft(draft) else "○"
    kind = {
        "identity": "Identity",
        "registry": "Registry",
        "document_presence": "Document",
        "turnover": "Turnover",
    }.get(item.renderer, "Review")
    return f"{marker} {kind} · {item.requirement_text}"


def _save_reviewer_callback(tender_root: str) -> None:
    set_reviewer(
        tender_root,
        str(st.session_state.get("reviewer_name", "")),
        str(st.session_state.get("reviewer_designation", "")),
    )


def _render_manual_routing(tender_root: Path, bidder_id: str, items: list[ReviewItem]) -> None:
    state = load_state(tender_root)
    routing = state.get("manual_routing", {}).get(bidder_id, {})
    st.markdown(
        f"<div class='manual-strip'><strong>{len(items)} conditions require manual review.</strong> "
        "Acknowledging this section routes the clauses; it does not mark them compliant or resolved.</div>",
        unsafe_allow_html=True,
    )
    with st.expander("View manual-review conditions", expanded=False):
        for item in items:
            st.markdown(f"**{', '.join(item.contributing_requirement_ids)}** · {item.requirement_text}")
            source = item.tender_sources[0] if item.tender_sources else {}
            st.caption(
                f"{item.requirement_type.replace('_', ' ').title()} · "
                f"{source.get('source_file') or 'Source unavailable'} · page {source.get('source_page') or '—'}"
            )
    acknowledged = st.checkbox(
        "I acknowledge that these conditions remain routed to manual review",
        value=bool(routing.get("acknowledged")),
        key=f"manual_ack_{bidder_id}",
    )
    note = st.text_area(
        "Manual-review routing note",
        value=str(routing.get("note", "")),
        key=f"manual_note_{bidder_id}",
        placeholder="For example: Routed to the ATC clause review sheet maintained by the scrutiny team.",
    )
    if st.button("Save manual-review routing", key=f"save_manual_{bidder_id}"):
        if acknowledged and not note.strip():
            st.error("Add a routing note before acknowledging the manual-review block.")
        else:
            set_manual_routing(
                tender_root,
                bidder_id,
                acknowledged=acknowledged,
                note=note,
            )
            st.success("Manual-review routing saved.")


def render(tender_root: Path | None) -> None:
    st.subheader("Review bidders")
    st.caption("Review system findings and evidence. This workspace does not qualify or reject bidders.")
    if tender_root is None:
        st.info("Open a processed tender workspace first.")
        return
    items = _cached_review_items(str(tender_root), artifact_fingerprint(tender_root))
    if not items:
        st.info("Review outputs are not available yet.")
        return
    import_legacy_turnover_reviews(tender_root, items)
    state = load_state(tender_root)
    grouped = review_items_by_bidder(items)

    if state.get("items") and state.get("artifact_fingerprint") != artifact_fingerprint(tender_root):
        conflicts = review_conflicts(items, state)
        st.warning(
            "Pipeline artifacts changed after review work began. "
            f"{len(conflicts['orphaned_decisions'])} stored decision(s) need manual reconciliation; "
            "nothing was remapped automatically."
        )

    reviewer = state.get("reviewer", {})
    st.session_state.setdefault("reviewer_name", reviewer.get("name", ""))
    st.session_state.setdefault("reviewer_designation", reviewer.get("designation", ""))
    with st.expander("Reviewer identity", expanded=not bool(reviewer.get("name"))):
        left, right = st.columns(2)
        left.text_input(
            "Reviewer name",
            key="reviewer_name",
            on_change=_save_reviewer_callback,
            args=(str(tender_root),),
        )
        right.text_input(
            "Designation",
            key="reviewer_designation",
            on_change=_save_reviewer_callback,
            args=(str(tender_root),),
        )
        st.caption("This identity is self-declared; the local activity log is not authentication-backed.")

    aliases = state.get("bidder_aliases", {})
    bidder_ids = sorted(grouped)
    bidder_labels = {
        bidder_id: aliases.get(bidder_id) or grouped[bidder_id][0].bidder_label or bidder_id
        for bidder_id in bidder_ids
    }
    queue_col, work_col, evidence_col = st.columns([0.78, 1.42, 1.1], gap="large")
    with queue_col:
        st.markdown("**Bidder queue**")
        selected_bidder = st.selectbox(
            "Selected bidder",
            bidder_ids,
            format_func=lambda value: bidder_labels[value],
            label_visibility="collapsed",
        )
        bidder_items = grouped[selected_bidder]
        assessable_items = [item for item in bidder_items if item.assessable]
        manual_items = [item for item in bidder_items if not item.assessable]
        valid = 0
        refreshed_state = load_state(tender_root)
        for item in assessable_items:
            draft = refreshed_state.get("items", {}).get(
                item_key(selected_bidder, item.requirement_fingerprint),
                {},
            )
            if not validate_item_draft(draft):
                valid += 1
        st.progress(valid / max(len(assessable_items), 1), text=f"{valid}/{len(assessable_items)} findings reviewed")
        review_status = refreshed_state.get("bidder_reviews", {}).get(selected_bidder, {}).get("status", "in progress")
        st.caption(f"Review status: {review_status.replace('_', ' ').title()}")

        alias_value = st.text_input(
            "Reviewer-facing bidder label",
            value=aliases.get(selected_bidder, ""),
            key=f"alias_{selected_bidder}",
            placeholder=bidder_labels[selected_bidder],
        )
        if st.button("Save bidder label", key=f"save_alias_{selected_bidder}", width="stretch"):
            set_bidder_alias(tender_root, selected_bidder, alias_value)
            st.success("Bidder label saved.")
            st.rerun()

        st.divider()
        review_record = refreshed_state.get("bidder_reviews", {}).get(selected_bidder, {})
        if review_record.get("status") == "completed":
            st.success("Bidder review completed.")
            with st.expander("Reopen review"):
                reason = st.text_area("Reason", key=f"reopen_reason_{selected_bidder}")
                if st.button("Reopen bidder review", key=f"reopen_{selected_bidder}"):
                    try:
                        reopen_bidder(tender_root, selected_bidder, reason)
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        st.rerun()
        else:
            if st.button("Complete bidder review", type="primary", width="stretch"):
                try:
                    complete_bidder(tender_root, items, selected_bidder)
                except ValueError as exc:
                    issue_lines = str(exc).splitlines()
                    st.error(f"Cannot complete yet. {issue_lines[0]}")
                    if len(issue_lines) > 1:
                        with st.expander(f"Show all {len(issue_lines)} outstanding items"):
                            for issue in issue_lines:
                                st.write(f"• {issue}")
                else:
                    st.rerun()

    state = load_state(tender_root)
    with work_col:
        st.markdown("**Review checklist**")
        filter_name = st.radio(
            "Checklist filter",
            ["All", "Unreviewed", "Needs attention"],
            horizontal=True,
            label_visibility="collapsed",
        )
        filtered = assessable_items
        if filter_name == "Unreviewed":
            filtered = [
                item
                for item in assessable_items
                if validate_item_draft(
                    state.get("items", {}).get(item_key(selected_bidder, item.requirement_fingerprint), {})
                )
            ]
        elif filter_name == "Needs attention":
            filtered = [
                item
                for item in assessable_items
                if "review" in item.system_status.casefold()
                or "not found" in item.system_status.casefold()
                or state.get("items", {})
                .get(item_key(selected_bidder, item.requirement_fingerprint), {})
                .get("outcome")
                in {"Needs clarification", "Incorrect extraction or mapping"}
            ]
        if not filtered:
            st.success("No checklist items match this filter.")
        else:
            fingerprints = [item.requirement_fingerprint for item in filtered]
            item_by_fp = {item.requirement_fingerprint: item for item in filtered}
            selected_fingerprint = st.selectbox(
                "Finding",
                fingerprints,
                format_func=lambda value: _item_label(item_by_fp[value], state),
                label_visibility="collapsed",
            )
            selected_item = item_by_fp[selected_fingerprint]
            documents = bidder_documents(tender_root, selected_bidder)
            decision_editor(str(tender_root), selected_item, documents)
        st.divider()
        _render_manual_routing(tender_root, selected_bidder, manual_items)

    with evidence_col:
        if filtered:
            evidence_viewer(str(tender_root), selected_item, documents)
        else:
            st.info("Choose another checklist filter to inspect evidence.")
