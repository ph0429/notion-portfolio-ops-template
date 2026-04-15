from __future__ import annotations

from textwrap import dedent

from openai import OpenAI

from portfolio_sync.models import (
    ApprovedCandidate,
    LivePortfolioPage,
    NotionPage,
    PortfolioTarget,
    RecommendationDraft,
    ReconciliationDraft,
)


class PortfolioReviewer:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def review_page(self, page: NotionPage, targets: list[PortfolioTarget]) -> RecommendationDraft:
        target_summary = "\n".join(
            f"- {target.title} | page_id={target.page_id} | managed_keys={','.join(target.managed_section_keys) or 'none'}"
            for target in targets[:50]
        )
        instructions = dedent(
            """
            You review work-notes content for a personal portfolio workflow.
            Return JSON only.
            Use these rules:
            - Prefer "ignore" for admin, routine status updates, meeting notes without outcomes, or weak signal work.
            - Use "create_page" for a strong new case study or portfolio story.
            - Use "update_page" only when the content clearly belongs on one existing portfolio page from the provided targets.
            - Suggested content should be concise markdown that can become a personal portfolio draft.
            - Do not mention the employer or client by name in suggested_title, portfolio_angle, suggested_content, or evidence_excerpt.
            - Replace company names such as "Threefold Energy" with generic phrases like "energy appraisal company", "startup", or "client team" when needed for context.
            - Focus on the work done, outcomes, systems built, technical decisions, and operating improvements rather than the company identity.
            - Never include confidential client names. Generalize all organization names unless the user explicitly asks to preserve them.
            """
        ).strip()

        user_prompt = dedent(
            f"""
            Review this work page and decide whether it should become a personal portfolio recommendation.

            Work page title: {page.title}
            Work page URL: {page.url}
            Created time: {page.created_time.isoformat()}
            Last edited time: {page.last_edited_time.isoformat()}

            Existing portfolio targets:
            {target_summary or "- none"}

            Work page content:
            {page.content}
            """
        ).strip()

        response = self.client.responses.parse(
            model=self.model,
            instructions=instructions,
            input=user_prompt,
            text_format=RecommendationDraft,
        )
        return response.output_parsed


class PortfolioReconciler:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def reconcile_candidate(
        self,
        candidate: ApprovedCandidate,
        live_pages: list[LivePortfolioPage],
        peer_candidates: list[ApprovedCandidate],
    ) -> ReconciliationDraft:
        live_summary = "\n".join(
            f"- live_page | id={page.page_id} | title={page.title} | url={page.url}\n  excerpt={page.content[:800]}"
            for page in live_pages
        )
        peer_summary = "\n".join(
            f"- candidate | id={peer.row_id} | title={peer.suggested_title or peer.title} | row_url={peer.row_url}\n  angle={peer.portfolio_angle}\n  excerpt={peer.suggested_content[:800]}"
            for peer in peer_candidates
        )
        instructions = dedent(
            """
            You reconcile approved personal portfolio candidates against live portfolio pages and other approved candidates.
            Return JSON only.
            Choose exactly one decision:
            - merge_into_live_page: candidate should be consolidated into one existing live portfolio page.
            - merge_with_candidate: candidate overlaps strongly with another approved candidate and should be merged before publication.
            - keep_separate: candidate is distinct and should remain its own page/story.
            - archive_candidate: candidate is duplicative, weaker than another item, or not worth carrying forward.

            Rules:
            - Use target_type=live_page only with merge_into_live_page.
            - Use target_type=candidate only with merge_with_candidate.
            - Use target_type=none and target_id="" for keep_separate or archive_candidate.
            - target_id must exactly match an id from the provided options.
            - Prefer merge_into_live_page when the live page already covers the same story and only needs the new material folded in.
            - Prefer merge_with_candidate when two approved candidates are really one portfolio story that should become one page.
            - Prefer keep_separate only when the candidate is materially distinct in scope, audience, or value.
            - Prefer archive_candidate when the candidate is duplicative and does not add enough unique value.
            - proposed_title should be the best end-state page title after reconciliation.
            - proposed_content should be concise markdown for the merged or retained end-state draft.
            - Do not mention employers or clients by name.
            """
        ).strip()

        user_prompt = dedent(
            f"""
            Candidate to reconcile:
            - row_id={candidate.row_id}
            - title={candidate.suggested_title or candidate.title}
            - source_url={candidate.source_url}
            - current_target_page_id={candidate.target_page_id}
            - current_target_page_url={candidate.target_page_url}
            - applied_page_url={candidate.applied_page_url}
            - recommendation_type={candidate.recommendation_type}
            - apply_state={candidate.apply_state}
            - portfolio_angle={candidate.portfolio_angle}
            - evidence_excerpt={candidate.evidence_excerpt}

            Candidate content:
            {candidate.suggested_content}

            Live portfolio page options:
            {live_summary or "- none"}

            Other approved candidate options:
            {peer_summary or "- none"}
            """
        ).strip()

        response = self.client.responses.parse(
            model=self.model,
            instructions=instructions,
            input=user_prompt,
            text_format=ReconciliationDraft,
        )
        return response.output_parsed
