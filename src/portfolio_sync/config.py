from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from dotenv import load_dotenv

from portfolio_sync.models import ReviewWindow

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _optional(name: str) -> str | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    return value.strip()


def _optional_csv(name: str) -> list[str]:
    value = _optional(name)
    if not value:
        return []
    parts = [item.strip() for item in value.replace("\n", ",").split(",")]
    return [item for item in parts if item]


def _parse_utc_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@dataclass(slots=True)
class ReviewConfig:
    work_notion_token: str
    work_notion_user_id: str
    personal_notion_token: str
    personal_notion_inbox_database_id: str
    personal_notion_publish_queue_database_id: str | None
    personal_notion_portfolio_parent_id: str | None
    personal_notion_portfolio_database_id: str | None
    personal_notion_target_page_ids: list[str]
    openai_api_key: str
    openai_model: str
    notion_version: str
    review_lookback_days: int
    review_window_start_override: str | None
    max_source_chars: int

    def review_window(self, mode: str) -> ReviewWindow:
        now = datetime.now(UTC)
        if mode == "bootstrap":
            return ReviewWindow(label="bootstrap", start=None, end=now)

        if self.review_window_start_override:
            start = _parse_utc_datetime(self.review_window_start_override)
        else:
            start = now - timedelta(days=self.review_lookback_days)

        label = f"{start.date().isoformat()}_to_{now.date().isoformat()}"
        return ReviewWindow(label=label, start=start, end=now)


@dataclass(slots=True)
class ApplyConfig:
    personal_notion_token: str
    personal_notion_inbox_database_id: str
    personal_notion_publish_queue_database_id: str | None
    personal_notion_portfolio_parent_id: str | None
    personal_notion_portfolio_database_id: str | None
    notion_version: str


@dataclass(slots=True)
class ReconcileConfig:
    personal_notion_token: str
    personal_notion_inbox_database_id: str
    personal_notion_publish_queue_database_id: str | None
    personal_notion_portfolio_database_id: str | None
    personal_notion_target_page_ids: list[str]
    personal_notion_reconciliation_database_id: str
    openai_api_key: str
    openai_model: str
    notion_version: str
    reconciliation_max_context_chars: int


def load_review_config() -> ReviewConfig:
    return ReviewConfig(
        work_notion_token=_require("WORK_NOTION_TOKEN"),
        work_notion_user_id=_require("WORK_NOTION_USER_ID"),
        personal_notion_token=_require("PERSONAL_NOTION_TOKEN"),
        personal_notion_inbox_database_id=_require("PERSONAL_NOTION_INBOX_DATABASE_ID"),
        personal_notion_publish_queue_database_id=_optional("PERSONAL_NOTION_PUBLISH_QUEUE_DATABASE_ID"),
        personal_notion_portfolio_parent_id=_optional("PERSONAL_NOTION_PORTFOLIO_PARENT_ID"),
        personal_notion_portfolio_database_id=_optional("PERSONAL_NOTION_PORTFOLIO_DATABASE_ID"),
        personal_notion_target_page_ids=_optional_csv("PERSONAL_NOTION_TARGET_PAGE_IDS"),
        openai_api_key=_require("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        notion_version=os.getenv("NOTION_VERSION", "2022-06-28"),
        review_lookback_days=int(os.getenv("REVIEW_LOOKBACK_DAYS", "8")),
        review_window_start_override=_optional("REVIEW_WINDOW_START"),
        max_source_chars=int(os.getenv("MAX_SOURCE_CHARS", "12000")),
    )


def load_apply_config() -> ApplyConfig:
    return ApplyConfig(
        personal_notion_token=_require("PERSONAL_NOTION_TOKEN"),
        personal_notion_inbox_database_id=_require("PERSONAL_NOTION_INBOX_DATABASE_ID"),
        personal_notion_publish_queue_database_id=_optional("PERSONAL_NOTION_PUBLISH_QUEUE_DATABASE_ID"),
        personal_notion_portfolio_parent_id=_optional("PERSONAL_NOTION_PORTFOLIO_PARENT_ID"),
        personal_notion_portfolio_database_id=_optional("PERSONAL_NOTION_PORTFOLIO_DATABASE_ID"),
        notion_version=os.getenv("NOTION_VERSION", "2022-06-28"),
    )


def load_reconcile_config() -> ReconcileConfig:
    return ReconcileConfig(
        personal_notion_token=_require("PERSONAL_NOTION_TOKEN"),
        personal_notion_inbox_database_id=_require("PERSONAL_NOTION_INBOX_DATABASE_ID"),
        personal_notion_publish_queue_database_id=_optional("PERSONAL_NOTION_PUBLISH_QUEUE_DATABASE_ID"),
        personal_notion_portfolio_database_id=_optional("PERSONAL_NOTION_PORTFOLIO_DATABASE_ID"),
        personal_notion_target_page_ids=_optional_csv("PERSONAL_NOTION_TARGET_PAGE_IDS"),
        personal_notion_reconciliation_database_id=_require("PERSONAL_NOTION_RECONCILIATION_DATABASE_ID"),
        openai_api_key=_require("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        notion_version=os.getenv("NOTION_VERSION", "2022-06-28"),
        reconciliation_max_context_chars=int(os.getenv("RECONCILIATION_MAX_CONTEXT_CHARS", "2500")),
    )
