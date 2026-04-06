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

    def test_english_feature_details_table_renders_as_sections(self) -> None:
        exporter = MarkdownExporter(base_url="https://confluence.example.com", page_id="123")
        html = (
            "<table><tbody>"
            "<tr><th>Feature</th><th>Details</th><th>Notes</th></tr>"
            "<tr><td>Login</td><td><p>Use SSO</p><ul><li>Google</li><li>Apple</li></ul></td><td>Required</td></tr>"
            "</tbody></table>"
        )

        result = exporter.convert_fragment(html)

        self.assertIn("#### Login", result)
        self.assertIn("Use SSO", result)
        self.assertIn("- Google", result)
        self.assertIn("- Apple", result)
        self.assertIn("**Notes:** Required", result)

    def test_korean_item_description_table_renders_as_sections(self) -> None:
        exporter = MarkdownExporter(base_url="https://confluence.example.com", page_id="123")
        html = (
            "<table><tbody>"
            "<tr><th>항목</th><th>설명</th><th>비고</th></tr>"
            "<tr><td>로그인</td><td><p>SSO 사용</p><ul><li>Google</li></ul></td><td>필수</td></tr>"
            "</tbody></table>"
        )

        result = exporter.convert_fragment(html)

        self.assertIn("#### 로그인", result)
        self.assertIn("SSO 사용", result)
        self.assertIn("- Google", result)
        self.assertIn("**비고:** 필수", result)

    def test_name_description_table_preserves_multiple_paragraphs(self) -> None:
        exporter = MarkdownExporter(base_url="https://confluence.example.com", page_id="123")
        html = (
            "<table><tbody>"
            "<tr><th>Name</th><th>Description</th></tr>"
            "<tr><td>Banner</td><td><p>Main hero</p><p>Seasonal only</p></td></tr>"
            "</tbody></table>"
        )

        result = exporter.convert_fragment(html)

        self.assertIn("#### Banner", result)
        self.assertIn("Main hero", result)
        self.assertIn("Seasonal only", result)

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
