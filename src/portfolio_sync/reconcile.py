from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from portfolio_sync.config import ReconcileConfig
from portfolio_sync.models import ApprovedCandidate, LivePortfolioPage, PortfolioTarget, ReconciliationDraft
from portfolio_sync.notion import NotionClient, normalize_title
from portfolio_sync.openai_client import PortfolioReconciler

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(slots=True)
class _ResolvedTarget:
    target_type: str
    target_id: str
    target_title: str
    target_url: str


def _write_github_summary(title: str, payload: dict[str, Any]) -> None:
    summary_path = None
    try:
        import os

        summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    except Exception:
        summary_path = None

    if not summary_path:
        return

    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write(f"## {title}\n\n")
        handle.write("```json\n")
        handle.write(json.dumps(payload, indent=2))
        handle.write("\n```\n")


def _summary_line(text: str) -> None:
    print(text)


def _tokens(value: str) -> set[str]:
    return {token for token in TOKEN_PATTERN.findall(value.casefold()) if len(token) > 2}


def _candidate_from_row(notion: NotionClient, row: dict) -> ApprovedCandidate:
    properties = row["properties"]
    return ApprovedCandidate(
        row_id=row["id"],
        row_url=row["url"],
        title=notion.page_title(row),
        source_page_id=notion._property_value(properties["Source Page ID"]),
        source_url=notion._property_value(properties["Source URL"]),
        recommendation_type=notion._property_value(properties["Recommendation Type"]),
        apply_state=notion._property_value(properties["Apply State"]),
        portfolio_angle=notion._property_value(properties["Portfolio Angle"]),
        suggested_title=notion._property_value(properties["Suggested Title"]),
        suggested_content=notion._property_value(properties["Suggested Content"]),
        evidence_excerpt=notion._property_value(properties["Evidence Excerpt"]),
        target_page_id=notion._property_value(properties["Target Page ID"]),
        target_page_url=notion._property_value(properties["Target Page URL"]),
        applied_page_id=notion._property_value(properties["Applied Page ID"]),
        applied_page_url=notion._property_value(properties["Applied Page URL"]),
    )


def _target_id_map(targets: list[PortfolioTarget]) -> dict[str, PortfolioTarget]:
    return {target.page_id: target for target in targets}


def _load_target_candidates(notion: NotionClient, config: ReconcileConfig) -> list[PortfolioTarget]:
    targets: dict[str, PortfolioTarget] = {}
    if config.personal_notion_portfolio_database_id:
        for target in notion.portfolio_targets_from_database(config.personal_notion_portfolio_database_id):
            targets[target.page_id] = target
    for target in notion.portfolio_targets_from_page_ids(config.personal_notion_target_page_ids):
        targets[target.page_id] = target
    return list(targets.values())


def _load_live_pages(notion: NotionClient, config: ReconcileConfig) -> list[LivePortfolioPage]:
    live_pages: list[LivePortfolioPage] = []
    for target in _load_target_candidates(notion, config):
        content = notion.page_content_as_text(target.page_id)[: config.reconciliation_max_context_chars]
        live_pages.append(
            LivePortfolioPage(
                page_id=target.page_id,
                title=target.title,
                url=target.url,
                content=content or target.title,
            )
        )
    return live_pages


def _live_page_score(candidate: ApprovedCandidate, page: LivePortfolioPage) -> int:
    score = 0
    candidate_title = candidate.suggested_title or candidate.title
    if normalize_title(candidate_title) == normalize_title(page.title):
        score += 100
    if candidate.target_page_id and candidate.target_page_id == page.page_id:
        score += 120

    candidate_tokens = _tokens(f"{candidate_title} {candidate.portfolio_angle} {candidate.evidence_excerpt}")
    page_tokens = _tokens(f"{page.title} {page.content[:500]}")
    score += len(candidate_tokens & page_tokens) * 8
    return score


def _peer_score(candidate: ApprovedCandidate, peer: ApprovedCandidate) -> int:
    score = 0
    candidate_title = candidate.suggested_title or candidate.title
    peer_title = peer.suggested_title or peer.title
    if normalize_title(candidate_title) == normalize_title(peer_title):
        score += 100
    if candidate.target_page_id and candidate.target_page_id == peer.target_page_id and candidate.target_page_id:
        score += 50

    candidate_tokens = _tokens(f"{candidate_title} {candidate.portfolio_angle} {candidate.evidence_excerpt}")
    peer_tokens = _tokens(f"{peer_title} {peer.portfolio_angle} {peer.evidence_excerpt}")
    score += len(candidate_tokens & peer_tokens) * 8
    return score


def _shortlist_live_pages(candidate: ApprovedCandidate, live_pages: list[LivePortfolioPage], limit: int = 6) -> list[LivePortfolioPage]:
    ranked = sorted(
        ((page, _live_page_score(candidate, page)) for page in live_pages),
        key=lambda item: item[1],
        reverse=True,
    )
    shortlisted = [page for page, score in ranked if score > 0][:limit]
    if shortlisted:
        return shortlisted
    return live_pages[: min(limit, len(live_pages))]


def _shortlist_peer_candidates(
    candidate: ApprovedCandidate, approved_candidates: list[ApprovedCandidate], limit: int = 5
) -> list[ApprovedCandidate]:
    peers = [peer for peer in approved_candidates if peer.row_id != candidate.row_id]
    ranked = sorted(
        ((peer, _peer_score(candidate, peer)) for peer in peers),
        key=lambda item: item[1],
        reverse=True,
    )
    shortlisted = [peer for peer, score in ranked if score > 0][:limit]
    if shortlisted:
        return shortlisted
    return peers[: min(limit, len(peers))]


def _resolve_target(
    draft: ReconciliationDraft,
    live_pages: list[LivePortfolioPage],
    peer_candidates: list[ApprovedCandidate],
) -> _ResolvedTarget:
    if draft.target_type == "live_page":
        page = next((page for page in live_pages if page.page_id == draft.target_id), None)
        if page:
            return _ResolvedTarget("live_page", page.page_id, page.title, page.url)
    if draft.target_type == "candidate":
        peer = next((peer for peer in peer_candidates if peer.row_id == draft.target_id), None)
        if peer:
            title = peer.suggested_title or peer.title
            return _ResolvedTarget("candidate", peer.row_id, title, peer.row_url)
    return _ResolvedTarget("none", "", "", "")


def _normalize_decision(decision: ReconciliationDraft, resolved_target: _ResolvedTarget) -> ReconciliationDraft:
    if decision.decision in {"merge_into_live_page", "merge_with_candidate"} and resolved_target.target_type == "none":
        return ReconciliationDraft(
            decision="keep_separate",
            confidence_score=decision.confidence_score,
            rationale=f"{decision.rationale}\n\nNo valid reconciliation target was resolved from the provided options.",
            target_type="none",
            target_id="",
            proposed_title=decision.proposed_title,
            proposed_content=decision.proposed_content,
        )
    return decision


def _payload(
    candidate: ApprovedCandidate,
    decision: ReconciliationDraft,
    resolved_target: _ResolvedTarget,
    review_status: str,
) -> dict[str, Any]:
    suggested_target = ""
    if resolved_target.target_type != "none":
        parts = [resolved_target.target_type]
        if resolved_target.target_title:
            parts.append(resolved_target.target_title)
        if resolved_target.target_id:
            parts.append(resolved_target.target_id)
        suggested_target = " | ".join(parts)

    return {
        "Title": decision.proposed_title or candidate.suggested_title or candidate.title,
        "Source Inbox Row ID": candidate.row_id,
        "Consolidation Decision": decision.decision,
        "Suggested Target": suggested_target,
        "Proposed Content": decision.proposed_content,
        "Review Status": review_status,
    }


def run_reconcile(mode: str, config: ReconcileConfig) -> dict[str, Any]:
    if mode != "approved":
        raise ValueError(f"Unsupported reconcile mode: {mode}")

    notion = NotionClient(config.personal_notion_token, config.notion_version)
    reconciler = PortfolioReconciler(config.openai_api_key, config.openai_model)
    live_pages = _load_live_pages(notion, config)
    if not live_pages:
        raise RuntimeError(
            "No live portfolio targets found. Set PERSONAL_NOTION_PORTFOLIO_DATABASE_ID and/or PERSONAL_NOTION_TARGET_PAGE_IDS."
        )

    approved_rows = notion.approved_inbox_rows(config.personal_notion_inbox_database_id)
    approved_candidates = [_candidate_from_row(notion, row) for row in approved_rows]
    stats: dict[str, Any] = {
        "mode": mode,
        "approved_candidates_seen": len(approved_candidates),
        "live_pages_loaded": len(live_pages),
        "reconciliation_rows_written": 0,
        "failed": 0,
    }

    for candidate in approved_candidates:
        try:
            live_shortlist = _shortlist_live_pages(candidate, live_pages)
            peer_shortlist = _shortlist_peer_candidates(candidate, approved_candidates)
            decision = reconciler.reconcile_candidate(candidate, live_shortlist, peer_shortlist)
            resolved_target = _resolve_target(decision, live_shortlist, peer_shortlist)
            decision = _normalize_decision(decision, resolved_target)
            resolved_target = _resolve_target(decision, live_shortlist, peer_shortlist)
            existing_row = notion.find_row_by_rich_text(
                config.personal_notion_reconciliation_database_id,
                "Source Inbox Row ID",
                candidate.row_id,
            )
            review_status = "new"
            if existing_row:
                review_status = notion._property_value(existing_row["properties"]["Review Status"]) or "new"
            payload = _payload(candidate, decision, resolved_target, review_status=review_status)
            properties = notion.build_properties(config.personal_notion_reconciliation_database_id, payload)
            if existing_row:
                notion.update_page_properties(existing_row["id"], properties)
            else:
                notion.create_page({"database_id": config.personal_notion_reconciliation_database_id}, properties, [])
            stats["reconciliation_rows_written"] += 1
            _summary_line(
                f"Reconciled {candidate.suggested_title or candidate.title} -> {decision.decision}"
            )
        except Exception as exc:
            stats["failed"] += 1
            _summary_line(f"Failed to reconcile {candidate.suggested_title or candidate.title}: {exc}")

    _write_github_summary("Portfolio Reconciliation Summary", stats)
    print(json.dumps(stats, indent=2))
    return stats


__all__ = ["run_reconcile"]
