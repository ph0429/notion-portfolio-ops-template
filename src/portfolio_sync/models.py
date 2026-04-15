from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RecommendationType = Literal["create_page", "update_page", "ignore"]
ApprovalStatus = Literal["new", "approved", "rejected", "needs_edit"]
ApplyState = Literal["pending", "applying", "applied", "failed", "skipped"]
ConsolidationDecisionType = Literal[
    "merge_into_live_page",
    "merge_with_candidate",
    "keep_separate",
    "archive_candidate",
]
TargetEntityType = Literal["live_page", "candidate", "none"]


class RecommendationDraft(BaseModel):
    recommendation_type: RecommendationType = Field(
        description="Whether to create a new portfolio page, update an existing one, or ignore the source page."
    )
    relevance_score: float = Field(ge=0, le=100)
    portfolio_angle: str
    suggested_title: str
    suggested_content: str
    evidence_excerpt: str
    target_hint: str = Field(
        description="Best-effort hint about which existing portfolio page should be updated. Leave blank when not applicable."
    )


class ReconciliationDraft(BaseModel):
    decision: ConsolidationDecisionType
    confidence_score: float = Field(ge=0, le=100)
    rationale: str
    target_type: TargetEntityType
    target_id: str = Field(
        description="Exact ID from the provided live pages or candidate pages. Leave blank when target_type is none."
    )
    proposed_title: str
    proposed_content: str


@dataclass(slots=True)
class NotionPage:
    page_id: str
    url: str
    title: str
    created_time: datetime
    last_edited_time: datetime
    created_by: str
    last_edited_by: str
    content: str


@dataclass(slots=True)
class PortfolioTarget:
    page_id: str
    title: str
    url: str
    managed_section_keys: list[str]


@dataclass(slots=True)
class LivePortfolioPage:
    page_id: str
    title: str
    url: str
    content: str


@dataclass(slots=True)
class ApprovedCandidate:
    row_id: str
    row_url: str
    title: str
    source_page_id: str
    source_url: str
    recommendation_type: str
    apply_state: str
    portfolio_angle: str
    suggested_title: str
    suggested_content: str
    evidence_excerpt: str
    target_page_id: str
    target_page_url: str
    applied_page_id: str
    applied_page_url: str


@dataclass(slots=True)
class InboxRecord:
    page_id: str
    title: str
    source_page_id: str
    approval_status: str
    apply_state: str
    recommendation_type: str
    target_page_id: str
    target_page_url: str
    managed_section_key: str


@dataclass(slots=True)
class ReviewWindow:
    label: str
    start: datetime | None
    end: datetime
