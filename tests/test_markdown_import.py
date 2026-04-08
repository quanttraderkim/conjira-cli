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
