import unittest

from portfolio_sync.models import ApprovedCandidate, LivePortfolioPage, ReconciliationDraft
from portfolio_sync.reconcile import _resolve_target, _shortlist_live_pages


def _candidate(**overrides: str) -> ApprovedCandidate:
    payload = {
        "row_id": "row-1",
        "row_url": "https://example.com/row-1",
        "title": "Base Title",
        "source_page_id": "source-1",
        "source_url": "https://example.com/source-1",
        "recommendation_type": "create_page",
        "apply_state": "pending",
        "portfolio_angle": "Automation and operating model work",
        "suggested_title": "AI Orchestration Systems",
        "suggested_content": "Detailed draft content",
        "evidence_excerpt": "Built automation foundations",
        "target_page_id": "",
        "target_page_url": "",
        "applied_page_id": "",
        "applied_page_url": "",
    }
    payload.update(overrides)
    return ApprovedCandidate(**payload)


class ReconcileLogicTest(unittest.TestCase):
    def test_shortlist_live_pages_prefers_exact_target_page_id(self) -> None:
        candidate = _candidate(target_page_id="page-2")
        live_pages = [
            LivePortfolioPage(page_id="page-1", title="General Portfolio", url="https://example.com/1", content="misc"),
            LivePortfolioPage(page_id="page-2", title="Different Title", url="https://example.com/2", content="misc"),
        ]

        shortlisted = _shortlist_live_pages(candidate, live_pages)

        self.assertEqual(shortlisted[0].page_id, "page-2")

    def test_resolve_target_returns_candidate_match(self) -> None:
        peer = _candidate(row_id="row-2", row_url="https://example.com/row-2", suggested_title="Merged Draft")
        decision = ReconciliationDraft(
            decision="merge_with_candidate",
            confidence_score=91,
            rationale="Overlap is strong",
            target_type="candidate",
            target_id="row-2",
            proposed_title="Merged Draft",
            proposed_content="Combined content",
        )

        resolved = _resolve_target(decision, [], [peer])

        self.assertEqual(resolved.target_type, "candidate")
        self.assertEqual(resolved.target_id, "row-2")
        self.assertEqual(resolved.target_title, "Merged Draft")


if __name__ == "__main__":
    unittest.main()
