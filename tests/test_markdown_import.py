import unittest

from conjira_cli.markdown_import import markdown_to_storage_html


class MarkdownImportTests(unittest.TestCase):
    def test_markdown_to_storage_html_handles_basic_blocks(self) -> None:
        result = markdown_to_storage_html(
            "\n".join(
                [
                    "---",
                    "title: Demo",
                    "---",
                    "",
                    "# Demo",
                    "",
                    "Paragraph with **bold** text.",
                    "",
                    "- Item A",
                    "- Item B",
                ]
            )
        )

        self.assertIn("<h1>Demo</h1>", result)
        self.assertIn("<p>Paragraph with <strong>bold</strong> text.</p>", result)
        self.assertIn("<ul><li>Item A</li><li>Item B</li></ul>", result)

    def test_markdown_to_storage_html_renders_links_and_images(self) -> None:
        result = markdown_to_storage_html(
            "See [docs](https://example.com) and [[Runbook|team runbook]].\n\n"
            "![chart](assets/chart.png)\n\n"
            "![[diagram.png]]"
        )

        self.assertIn('<a href="https://example.com">docs</a>', result)
        self.assertIn('<ri:page ri:content-title="Runbook" />', result)
        self.assertIn("<![CDATA[team runbook]]>", result)
        self.assertIn('<ri:attachment ri:filename="chart.png" />', result)
        self.assertIn('<ri:attachment ri:filename="diagram.png" />', result)

    def test_markdown_to_storage_html_renders_tables_and_code_blocks(self) -> None:
        result = markdown_to_storage_html(
            "\n".join(
                [
                    "| Name | Value |",
                    "| --- | --- |",
                    "| Demo | 1 |",
                    "",
                    "```python",
                    "print('ok')",
                    "```",
                ]
            )
        )

        self.assertIn("<table><tbody>", result)
        self.assertIn("<th>Name</th>", result)
        self.assertIn("<td>Demo</td>", result)
        self.assertIn('<ac:structured-macro ac:name="code"', result)
        self.assertIn('<ac:parameter ac:name="language">python</ac:parameter>', result)
        self.assertIn("<![CDATA[print('ok')]]>", result)

    def test_markdown_to_storage_html_renders_mermaid_macro_when_configured(self) -> None:
        result = markdown_to_storage_html(
            "\n".join(
                [
                    "```mermaid",
                    "graph TD",
                    "A-->B",
                    "```",
                ]
            ),
            mermaid_macro_name="mermaid-macro",
        )

        self.assertIn('<ac:structured-macro ac:name="mermaid-macro"', result)
        self.assertIn("<![CDATA[graph TD\nA-->B]]>", result)
        self.assertNotIn('<ac:structured-macro ac:name="code"', result)

    def test_markdown_to_storage_html_keeps_mermaid_as_code_without_config(self) -> None:
        result = markdown_to_storage_html(
            "\n".join(
                [
                    "```mermaid",
                    "graph TD",
                    "A-->B",
                    "```",
                ]
            )
        )

        self.assertIn('<ac:structured-macro ac:name="code"', result)
        self.assertIn('<ac:parameter ac:name="language">mermaid</ac:parameter>', result)

    def test_markdown_to_storage_html_renders_callout_macro(self) -> None:
        result = markdown_to_storage_html(
            "\n".join(
                [
                    "> [!INFO] Setup note",
                    "> Use a PAT stored in Keychain.",
                    ">",
                    "> Run auth-check after setup.",
                ]
            )
        )

        self.assertIn('<ac:structured-macro ac:name="info"', result)
        self.assertIn('<ac:parameter ac:name="title">Setup note</ac:parameter>', result)
        self.assertIn("<ac:rich-text-body>", result)
        self.assertIn("<p>Use a PAT stored in Keychain.</p>", result)
        self.assertIn("<p>Run auth-check after setup.</p>", result)

    def test_markdown_to_storage_html_renders_expand_macro(self) -> None:
        result = markdown_to_storage_html(
            "\n".join(
                [
                    "> [!EXPAND] Detailed rollout plan",
                    "> Step 1",
                    ">",
                    "> Step 2",
                ]
            )
        )

        self.assertIn('<ac:structured-macro ac:name="expand"', result)
        self.assertIn('<ac:parameter ac:name="title">Detailed rollout plan</ac:parameter>', result)
        self.assertIn("<ac:rich-text-body>", result)
        self.assertIn("<p>Step 1</p>", result)
        self.assertIn("<p>Step 2</p>", result)

    def test_markdown_to_storage_html_renders_status_macro_inline(self) -> None:
        result = markdown_to_storage_html(
            "Current state: :status[In Progress]{color=yellow}"
        )

        self.assertIn('<ac:structured-macro ac:name="status"', result)
        self.assertIn('<ac:parameter ac:name="colour">Yellow</ac:parameter>', result)
        self.assertIn('<ac:parameter ac:name="title">In Progress</ac:parameter>', result)

    def test_markdown_to_storage_html_renders_status_macro_in_table_cell(self) -> None:
        result = markdown_to_storage_html(
            "\n".join(
                [
                    "| Item | Status |",
                    "| --- | --- |",
                    "| API | :status[Planned]{color=blue} |",
                ]
            )
        )

        self.assertIn("<table><tbody>", result)
        self.assertIn('<ac:structured-macro ac:name="status"', result)
        self.assertIn('<ac:parameter ac:name="colour">Blue</ac:parameter>', result)
        self.assertIn('<ac:parameter ac:name="title">Planned</ac:parameter>', result)

    def test_xhtml_self_closing_br_tags(self) -> None:
        """<br> must be emitted as <br /> for Confluence XHTML strict mode."""
        # The current renderer doesn't emit bare <br> from markdown, but
        # if inline HTML sneaks through we need the post-processor to fix it.
        from conjira_cli.markdown_import import _ensure_xhtml_self_closing

        self.assertEqual(_ensure_xhtml_self_closing("<br>"), "<br />")
        self.assertEqual(_ensure_xhtml_self_closing("<br/>"), "<br />")
        self.assertEqual(_ensure_xhtml_self_closing("<br />"), "<br />")
        self.assertEqual(_ensure_xhtml_self_closing("<hr>"), "<hr />")
        self.assertEqual(
            _ensure_xhtml_self_closing("<p>text<br>more</p>"),
            "<p>text<br />more</p>",
        )

    def test_xhtml_self_closing_preserves_attributes(self) -> None:
        from conjira_cli.markdown_import import _ensure_xhtml_self_closing

        self.assertEqual(
            _ensure_xhtml_self_closing('<hr class="divider">'),
            '<hr class="divider" />',
        )

    def test_xhtml_self_closing_img_tag(self) -> None:
        from conjira_cli.markdown_import import _ensure_xhtml_self_closing

        self.assertEqual(
            _ensure_xhtml_self_closing('<img src="x.png">'),
            '<img src="x.png" />',
        )

    def test_output_is_valid_xhtml(self) -> None:
        """Full markdown-to-HTML output must be well-formed XHTML."""
        import xml.etree.ElementTree as ET

        result = markdown_to_storage_html(
            "# Hello\n\nParagraph with **bold**.\n\n---\n"
        )
        wrapped = f'<root xmlns:ac="urn:ac" xmlns:ri="urn:ri">{result}</root>'
        # Should not raise
        ET.fromstring(wrapped)
