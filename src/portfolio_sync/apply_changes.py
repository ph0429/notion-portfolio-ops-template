from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from portfolio_sync.config import ApplyConfig
from portfolio_sync.markdown_blocks import (
    chunked,
    managed_section_content_blocks,
    managed_section_markers,
    markdown_to_blocks,
)
from portfolio_sync.notion import NotionClient


def _write_github_summary(title: str, payload: dict[str, Any]) -> None:
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


def _append_children_in_batches(notion: NotionClient, block_id: str, children: list[dict], after: str | None = None) -> None:
    anchor = after
    for batch in chunked(children, 50):
        response = notion.append_block_children(block_id, batch, after=anchor)
        results = response.get("results", [])
        if results:
            anchor = results[-1]["id"]


def _property_value(notion: NotionClient, row: dict, property_name: str) -> str:
    return notion._property_value(row["properties"][property_name])


def _set_row_state(notion: NotionClient, database_id: str, row_id: str, **updates: Any) -> None:
    properties = notion.build_properties(database_id, updates)
    notion.update_page_properties(row_id, properties)


def _find_marker_range(notion: NotionClient, page_id: str, key: str) -> tuple[str, str, list[dict]]:
    start_marker, end_marker = managed_section_markers(key)
    children = notion.list_block_children(page_id)
    start_id = ""
    end_id = ""
    for block in children:
        text = notion.block_plain_text(block)
        if text == start_marker:
            start_id = block["id"]
        if text == end_marker:
            end_id = block["id"]
    if not start_id or not end_id:
        raise RuntimeError(f"Managed section markers not found for key '{key}' on page {page_id}.")
    return start_id, end_id, children


def _today_iso() -> str:
    return datetime.now(UTC).date().isoformat()


def _staged_update_blocks(
    suggested_title: str,
    suggested_content: str,
    source_url: str,
    target_page_url: str,
    managed_section_key: str,
) -> list[dict]:
    intro_lines = [
        "## Suggested update",
        f"Target page: {target_page_url or 'Unknown target'}",
        f"Managed section key: {managed_section_key}",
    ]
    if source_url:
        intro_lines.append(f"Source page: {source_url}")
    intro_lines.append("")
    intro_lines.append(suggested_content)
    body = "\n".join(intro_lines)
    return markdown_to_blocks(body)


def run_apply(mode: str, config: ApplyConfig) -> dict[str, Any]:
    if mode != "approved":
        raise ValueError(f"Unsupported apply mode: {mode}")

    notion = NotionClient(config.personal_notion_token, config.notion_version)
    rows = notion.approved_rows(config.personal_notion_inbox_database_id)
    stats: dict[str, Any] = {"mode": mode, "rows_seen": len(rows), "applied": 0, "failed": 0}

    for row in rows:
        row_id = row["id"]
        recommendation_type = _property_value(notion, row, "Recommendation Type")
        suggested_title = _property_value(notion, row, "Suggested Title") or _property_value(notion, row, "Title")
        suggested_content = _property_value(notion, row, "Suggested Content")
        source_url = _property_value(notion, row, "Source URL")
        target_page_id = _property_value(notion, row, "Target Page ID")
        target_page_url = _property_value(notion, row, "Target Page URL")
        managed_section_key = _property_value(notion, row, "Managed Section Key")
        if not managed_section_key:
            managed_section_key = f"row_{row_id.replace('-', '')[:12]}"

        try:
            _set_row_state(
                notion,
                config.personal_notion_inbox_database_id,
                row_id,
                **{"Apply State": "applying", "Last Error": ""},
            )

            blocks = managed_section_content_blocks(managed_section_key, suggested_content, source_url=source_url)

            if recommendation_type == "create_page":
                if config.personal_notion_publish_queue_database_id:
                    created = notion.create_page_in_database(
                        config.personal_notion_publish_queue_database_id,
                        suggested_title,
                        blocks,
                    )
                elif config.personal_notion_portfolio_database_id:
                    created = notion.create_page_in_database(
                        config.personal_notion_portfolio_database_id,
                        suggested_title,
                        blocks,
                    )
                elif config.personal_notion_portfolio_parent_id:
                    created = notion.create_page_under_parent(
                        config.personal_notion_portfolio_parent_id,
                        suggested_title,
                        blocks,
                    )
                else:
                    raise RuntimeError(
                        "Missing PERSONAL_NOTION_PUBLISH_QUEUE_DATABASE_ID, PERSONAL_NOTION_PORTFOLIO_DATABASE_ID, or PERSONAL_NOTION_PORTFOLIO_PARENT_ID."
                    )

                _set_row_state(
                    notion,
                    config.personal_notion_inbox_database_id,
                    row_id,
                    **{
                        "Apply State": "applied",
                        "Applied At": _today_iso(),
                        "Applied Page ID": created["id"],
                        "Applied Page URL": created["url"],
                        "Target Page ID": created["id"],
                        "Target Page URL": created["url"],
                    },
                )
            elif recommendation_type == "update_page":
                if not target_page_id:
                    raise RuntimeError("Target Page ID is required for update_page recommendations.")
                if config.personal_notion_publish_queue_database_id:
                    staged_title = f"Update Draft: {suggested_title}"
                    staged_blocks = _staged_update_blocks(
                        suggested_title=suggested_title,
                        suggested_content=suggested_content,
                        source_url=source_url,
                        target_page_url=target_page_url,
                        managed_section_key=managed_section_key,
                    )
                    created = notion.create_page_in_database(
                        config.personal_notion_publish_queue_database_id,
                        staged_title,
                        staged_blocks,
                    )
                    _set_row_state(
                        notion,
                        config.personal_notion_inbox_database_id,
                        row_id,
                        **{
                            "Apply State": "applied",
                            "Applied At": _today_iso(),
                            "Applied Page ID": created["id"],
                            "Applied Page URL": created["url"],
                        },
                    )
                else:
                    start_id, end_id, children = _find_marker_range(notion, target_page_id, managed_section_key)
                    deleting = False
                    for block in children:
                        if block["id"] == start_id:
                            deleting = True
                            continue
                        if block["id"] == end_id:
                            break
                        if deleting:
                            notion.archive_block(block["id"])

                    _append_children_in_batches(notion, target_page_id, blocks[1:-1], after=start_id)
                    _set_row_state(
                        notion,
                        config.personal_notion_inbox_database_id,
                        row_id,
                        **{
                            "Apply State": "applied",
                            "Applied At": _today_iso(),
                            "Applied Page ID": target_page_id,
                            "Applied Page URL": target_page_url,
                        },
                    )
            else:
                raise RuntimeError(f"Unsupported recommendation type: {recommendation_type}")

            stats["applied"] += 1
        except Exception as exc:
            stats["failed"] += 1
            _set_row_state(
                notion,
                config.personal_notion_inbox_database_id,
                row_id,
                **{
                    "Apply State": "failed",
                    "Last Error": str(exc),
                },
            )

    _write_github_summary("Apply Approved Summary", stats)
    print(json.dumps(stats, indent=2))
    return stats


__all__ = ["run_apply"]
