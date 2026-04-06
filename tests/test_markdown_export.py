import unittest

from conjira_cli.markdown_export import MarkdownExporter


class MarkdownExportTests(unittest.TestCase):
    def test_convert_fragment_handles_basic_structures(self) -> None:
        exporter = MarkdownExporter(base_url="https://confluence.example.com", page_id="123")
        html = (
            "<h2>Service overview</h2>"
            "<p><strong>Goal</strong> test</p>"
            "<ul><li>Item A</li><li>Item B</li></ul>"
            "<table><tbody><tr><th>Section</th><th>Content</th></tr><tr><td>A</td><td>B</td></tr></tbody></table>"
            '<p><ac:image><ri:attachment ri:filename="demo.png" /></ac:image></p>'
        )

        result = exporter.convert_fragment(html)

        self.assertIn("## Service overview", result)
        self.assertIn("**Goal** test", result)
        self.assertIn("- Item A", result)
        self.assertIn("#### A", result)
        self.assertIn("B", result)
        self.assertIn("![demo.png](https://confluence.example.com/download/attachments/123/demo.png)", result)

    def test_structured_table_renders_as_sections(self) -> None:
        exporter = MarkdownExporter(base_url="https://confluence.example.com", page_id="123")
        html = (
            "<table><tbody>"
            "<tr><th>Section</th><th>Content</th><th>Notes</th></tr>"
            "<tr><td>Entry point</td><td><ul><li>Top of the settings tab</li></ul></td><td>See image</td></tr>"
            "</tbody></table>"
        )

        result = exporter.convert_fragment(html)

        self.assertIn("#### Entry point", result)
        self.assertIn("- Top of the settings tab", result)
        self.assertIn("**Notes:** See image", result)

    def test_image_is_separated_from_text(self) -> None:
        exporter = MarkdownExporter(base_url="https://confluence.example.com", page_id="123")
        html = (
            "<p>See image"
            '<ac:image><ri:attachment ri:filename="demo.png" /></ac:image>'
            "</p>"
        )

        result = exporter.convert_fragment(html)

        self.assertIn("See image\n\n![demo.png]", result)

    def test_malformed_mixed_emphasis_is_flattened(self) -> None:
        exporter = MarkdownExporter(base_url="https://confluence.example.com", page_id="123")
        html = "<ul><li><em>Description <strong>emphasis</strong></em></li></ul>"

        result = exporter.convert_fragment(html)

        self.assertIn("- Description emphasis", result)
