from __future__ import annotations

import json
from typing import Any

from portfolio_sync.config import ReviewConfig
from portfolio_sync.models import InboxRecord, PortfolioTarget, RecommendationDraft, ReviewWindow
from portfolio_sync.notion import NotionClient, normalize_title, parse_notion_datetime
from portfolio_sync.openai_client import PortfolioReviewer


def stable_managed_section_key(source_page_id: str) -> str:
    return f"src_{source_page_id.replace('-', '')[:12]}"


def select_target(
    recommendation: RecommendationDraft,
    targets: list[PortfolioTarget],
    allow_unmanaged_targets: bool = False,
) -> PortfolioTarget | None:
    if recommendation.recommendation_type != "update_page":
        return None

    desired = normalize_title(recommendation.target_hint or recommendation.suggested_title)
    if not desired:
        return None

    for target in targets:
        if normalize_title(target.title) != desired:
            continue
        if allow_unmanaged_targets or target.managed_section_keys:
            return target
    return None


def should_process_page(page: dict, work_user_id: str, window: ReviewWindow) -> bool:
    created_by = page.get("created_by", {}).get("id")
    last_edited_by = page.get("last_edited_by", {}).get("id")
    if created_by != work_user_id and last_edited_by != work_user_id:
        return False

    if window.start is None:
        return True

    last_edited_time = parse_notion_datetime(page["last_edited_time"])
    return last_edited_time >= window.start


def _summary_line(text: str) -> None:
    print(text)


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


def _upsert_payload(
    recommendation: RecommendationDraft,
    source_page: dict,
    managed_section_key: str,
    review_window_label: str,
    target: PortfolioTarget | None,
) -> dict[str, Any]:
    recommendation_type = recommendation.recommendation_type
    if recommendation_type == "update_page" and not target:
        recommendation_type = "create_page"

    return {
        "Title": recommendation.suggested_title or source_page["title"],
        "Source Page ID": source_page["page_id"],
        "Source URL": source_page["url"],
        "Source Workspace": "work",
        "Source Created Time": source_page["created_time"],
        "Source Last Edited Time": source_page["last_edited_time"],
        "Review Window": review_window_label,
        "Recommendation Type": recommendation_type,
        "Relevance Score": round(recommendation.relevance_score, 2),
        "Portfolio Angle": recommendation.portfolio_angle,
        "Suggested Title": recommendation.suggested_title,
        "Suggested Content": recommendation.suggested_content,
        "Evidence Excerpt": recommendation.evidence_excerpt,
        "Target Page ID": target.page_id if target else "",
        "Target Page URL": target.url if target else "",
        "Managed Section Key": (
            target.managed_section_keys[0] if target and target.managed_section_keys else managed_section_key
        ),
        "Last Error": "",
    }


def _reset_or_preserve_state(existing: InboxRecord | None, payload: dict[str, Any]) -> dict[str, Any]:
    if existing is None:
        payload["Approval Status"] = "new"
        payload["Apply State"] = "pending"
        payload["Applied At"] = None
        payload["Applied Page ID"] = ""
        payload["Applied Page URL"] = ""
        return payload

    if existing.apply_state == "applied":
        payload["Approval Status"] = "new"
        payload["Apply State"] = "pending"
        payload["Applied At"] = None
        payload["Applied Page ID"] = ""
        payload["Applied Page URL"] = ""
        return payload

    payload["Approval Status"] = existing.approval_status or "new"
    payload["Apply State"] = existing.apply_state or "pending"
    return payload


def run_review(mode: str, config: ReviewConfig) -> dict[str, Any]:
    work_notion = NotionClient(config.work_notion_token, config.notion_version)
    personal_notion = NotionClient(config.personal_notion_token, config.notion_version)
    reviewer = PortfolioReviewer(config.openai_api_key, config.openai_model)
    window = config.review_window(mode)

    targets: list[PortfolioTarget] = []
    target_database_id = (
        config.personal_notion_portfolio_database_id or config.personal_notion_publish_queue_database_id
    )
    if target_database_id:
        targets = personal_notion.portfolio_targets_from_database(target_database_id)
    if config.personal_notion_target_page_ids:
        explicit_targets = personal_notion.portfolio_targets_from_page_ids(config.personal_notion_target_page_ids)
        targets_by_id = {target.page_id: target for target in targets}
        for target in explicit_targets:
            targets_by_id[target.page_id] = target
        targets = list(targets_by_id.values())

    pages = work_notion.search_pages()
    stats: dict[str, Any] = {
        "mode": mode,
        "window_label": window.label,
        "pages_seen": 0,
        "pages_processed": 0,
        "recommendations_written": 0,
        "ignored": 0,
        "targets_loaded": len(targets),
    }

    for page in pages:
        stats["pages_seen"] += 1
        if not should_process_page(page, config.work_notion_user_id, window):
            continue

        content = work_notion.page_content_as_text(page["id"])[: config.max_source_chars]
        notion_page = work_notion.parse_page_to_notion_page(page, content or work_notion.page_title(page))
        source = {
            "page_id": notion_page.page_id,
            "title": notion_page.title,
            "url": notion_page.url,
            "created_time": notion_page.created_time.date().isoformat(),
            "last_edited_time": notion_page.last_edited_time.date().isoformat(),
        }
        recommendation = reviewer.review_page(notion_page, targets)
        if recommendation.recommendation_type == "ignore":
            stats["ignored"] += 1
            continue

        target = select_target(
            recommendation,
            targets,
            allow_unmanaged_targets=bool(config.personal_notion_publish_queue_database_id),
        )
        managed_section_key = stable_managed_section_key(notion_page.page_id)
        payload = _upsert_payload(recommendation, source, managed_section_key, window.label, target)
        existing_row = personal_notion.find_inbox_row(
            config.personal_notion_inbox_database_id, notion_page.page_id
        )
        existing = personal_notion.inbox_record_from_page(existing_row) if existing_row else None
        payload = _reset_or_preserve_state(existing, payload)
        properties = personal_notion.build_properties(config.personal_notion_inbox_database_id, payload)

        if existing_row:
            personal_notion.update_page_properties(existing_row["id"], properties)
        else:
            personal_notion.create_page(
                {"database_id": config.personal_notion_inbox_database_id},
                properties,
                [],
            )
        stats["pages_processed"] += 1
        stats["recommendations_written"] += 1
        _summary_line(f"Processed {notion_page.title} -> {payload['Recommendation Type']}")

    _write_github_summary("Weekly Review Summary", stats)
    print(json.dumps(stats, indent=2))
    return stats


__all__ = [
    "run_review",
    "select_target",
    "stable_managed_section_key",
    "should_process_page",
]
