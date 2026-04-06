import unittest

from conjira_cli.inline_comments import (
    build_inline_comment_summary,
    render_inline_comment_summary_markdown,
)


class InlineCommentTests(unittest.TestCase):
    def test_build_inline_comment_summary_groups_blank_reply_with_previous_anchor(self) -> None:
        raw_comments = [
            {
                "id": "1",
                "history": {
                    "createdDate": "2026-04-02T10:00:00+09:00",
                    "createdBy": {"displayName": "Reviewer A"},
                },
                "body": {"storage": {"value": "<p>Please confirm the banner assets.</p>"}},
                "extensions": {
                    "inlineProperties": {
                        "originalSelection": "(Needs review) provided assets",
                        "markerRef": "marker-1",
                    },
                    "resolution": {"status": "resolved"},
                },
                "_links": {"webui": "/comment-1"},
            },
            {
                "id": "2",
                "history": {
                    "createdDate": "2026-04-02T10:05:00+09:00",
                    "createdBy": {"displayName": "Reviewer B"},
                },
                "body": {"storage": {"value": "<p>For the banner, include the logo, hero image, and app icon.</p>"}},
                "extensions": {
                    "inlineProperties": {
                        "originalSelection": "",
                        "markerRef": "",
                    },
                    "resolution": {"status": "open"},
                },
                "_links": {"webui": "/comment-2"},
            },
        ]

        summary = build_inline_comment_summary(
            base_url="https://confluence.example.com",
            page_id="123",
            page_title="Demo",
            page_url="https://confluence.example.com/pages/123",
            raw_comments=raw_comments,
        )

        self.assertEqual(summary["total_comments"], 2)
        self.assertEqual(summary["thread_count"], 1)
        self.assertEqual(summary["open_thread_count"], 1)
        thread = summary["threads"][0]
        self.assertEqual(thread["selection"], "(Needs review) provided assets")
        self.assertEqual(thread["comment_count"], 2)
        self.assertEqual(thread["status"], "open")
        self.assertEqual(
            thread["latest_comment_excerpt"],
            "For the banner, include the logo, hero image, and app icon.",
        )

    def test_render_inline_comment_summary_markdown_contains_core_sections(self) -> None:
        summary = {
            "page_id": "123",
            "page_title": "Demo",
            "page_url": "https://confluence.example.com/pages/123",
            "status_filter": "open",
            "total_comments": 2,
            "all_comment_count": 5,
            "matching_comment_count": 2,
            "anchored_comment_count": 1,
            "reply_comment_count": 1,
            "thread_count": 1,
            "open_thread_count": 1,
            "status_counts": {"open": 2, "resolved": 0, "dangling": 0},
            "thread_status_counts": {"open": 1},
            "threads": [
                {
                    "selection": "Reward entry flow",
                    "status": "open",
                    "comment_count": 2,
                    "participants": ["Reviewer A", "Reviewer B"],
                    "latest_comment_at": "2026-04-02T10:10:00+09:00",
                    "latest_comment_excerpt": "Pick one of the two reward variants instead of showing both.",
                    "latest_comment_url": "https://confluence.example.com/comment-1",
                }
            ],
        }

        markdown = render_inline_comment_summary_markdown(summary)

        self.assertIn("# Demo - Inline Comment Summary", markdown)
        self.assertIn("## Quick Summary", markdown)
        self.assertIn("## Threads", markdown)
        self.assertIn("### Open", markdown)
        self.assertIn("Pick one of the two reward variants instead of showing both.", markdown)
