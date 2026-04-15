import unittest

from portfolio_sync.markdown_blocks import managed_section_content_blocks, managed_section_markers, markdown_to_blocks


class MarkdownBlocksTest(unittest.TestCase):
    def test_markdown_to_blocks_preserves_headings_and_lists(self) -> None:
        blocks = markdown_to_blocks("# Title\n\nParagraph line\n- First\n1. Second")
        self.assertEqual(blocks[0]["type"], "heading_1")
        self.assertEqual(blocks[1]["type"], "paragraph")
        self.assertEqual(blocks[2]["type"], "bulleted_list_item")
        self.assertEqual(blocks[3]["type"], "numbered_list_item")

    def test_managed_section_content_blocks_wraps_content(self) -> None:
        blocks = managed_section_content_blocks("demo", "## Draft\nHello", source_url="https://example.com")
        start, end = managed_section_markers("demo")
        self.assertIn(start, blocks[1]["paragraph"]["rich_text"][0]["text"]["content"])
        self.assertIn(end, blocks[-1]["paragraph"]["rich_text"][0]["text"]["content"])


if __name__ == "__main__":
    unittest.main()

