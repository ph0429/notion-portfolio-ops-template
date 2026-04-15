import unittest
from datetime import UTC, datetime, timedelta

from portfolio_sync.models import PortfolioTarget, RecommendationDraft, ReviewWindow
from portfolio_sync.review import select_target, should_process_page, stable_managed_section_key


class ReviewLogicTest(unittest.TestCase):
    def test_select_target_requires_marker_key(self) -> None:
        recommendation = RecommendationDraft(
            recommendation_type="update_page",
            relevance_score=90,
            portfolio_angle="Strong launch story",
            suggested_title="Energy Platform Delivery",
            suggested_content="Draft content",
            evidence_excerpt="Shipped milestone",
            target_hint="Energy Platform Delivery",
        )
        targets = [
            PortfolioTarget(page_id="1", title="Energy Platform Delivery", url="https://example.com/1", managed_section_keys=[]),
            PortfolioTarget(page_id="2", title="Energy Platform Delivery", url="https://example.com/2", managed_section_keys=["demo"]),
        ]
        selected = select_target(recommendation, targets)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.page_id, "2")

    def test_select_target_allows_unmanaged_targets_when_enabled(self) -> None:
        recommendation = RecommendationDraft(
            recommendation_type="update_page",
            relevance_score=90,
            portfolio_angle="Strong launch story",
            suggested_title="AI Orchestration Systems and Operational Infrastructure",
            suggested_content="Draft content",
            evidence_excerpt="Shipped milestone",
            target_hint="AI Orchestration Systems and Operational Infrastructure",
        )
        targets = [
            PortfolioTarget(
                page_id="1",
                title="AI Orchestration Systems and Operational Infrastructure",
                url="https://example.com/1",
                managed_section_keys=[],
            )
        ]
        selected = select_target(recommendation, targets, allow_unmanaged_targets=True)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.page_id, "1")

    def test_should_process_page_checks_user_and_window(self) -> None:
        now = datetime.now(UTC)
        page = {
            "created_by": {"id": "user-1"},
            "last_edited_by": {"id": "user-2"},
            "last_edited_time": now.isoformat().replace("+00:00", "Z"),
        }
        window = ReviewWindow(label="weekly", start=now - timedelta(days=1), end=now)
        self.assertTrue(should_process_page(page, "user-1", window))
        self.assertFalse(should_process_page(page, "user-3", window))

    def test_stable_managed_section_key_is_stable(self) -> None:
        self.assertEqual(stable_managed_section_key("abcd-1234"), "src_abcd1234")


if __name__ == "__main__":
    unittest.main()
