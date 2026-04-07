import unittest

from conjira_cli.section_edit import SectionEditError, replace_section_html


class SectionEditTests(unittest.TestCase):
    def test_replace_section_html_replaces_heading_block_until_next_peer_heading(self) -> None:
        body_html = (
            "<h1>Guide</h1>"
            "<p>Intro</p>"
            "<h2>Install</h2>"
            "<p>Old install step</p>"
            "<h3>Nested detail</h3>"
            "<p>Nested note</p>"
            "<h2>Usage</h2>"
            "<p>Run command</p>"
        )

        result = replace_section_html(
            body_html,
            heading="Install",
            replacement_html="<p>New install step</p><ul><li>Do this first</li></ul>",
        )

        self.assertEqual(result.matched_heading, "Install")
        self.assertEqual(result.heading_level, 2)
        self.assertIn("<p>Old install step</p>", result.old_section_html)
        self.assertIn("<h3>Nested detail</h3>", result.old_section_html)
        self.assertIn("<p>New install step</p>", result.new_section_html)
        self.assertIn("<ul><li>Do this first</li></ul>", result.updated_body_html)
        self.assertIn("<h2>Usage</h2>", result.updated_body_html)
        self.assertNotIn("Old install step", result.updated_body_html)

    def test_replace_section_html_fails_when_heading_missing(self) -> None:
        with self.assertRaises(SectionEditError):
            replace_section_html(
                "<h1>Guide</h1><p>Body</p>",
                heading="Install",
                replacement_html="<p>Replacement</p>",
            )

    def test_replace_section_html_fails_when_heading_ambiguous(self) -> None:
        with self.assertRaises(SectionEditError):
            replace_section_html(
                "<h2>Install</h2><p>A</p><h2>Install</h2><p>B</p>",
                heading="Install",
                replacement_html="<p>Replacement</p>",
            )
