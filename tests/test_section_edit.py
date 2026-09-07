import unittest

from conjira_cli.section_edit import (
    SectionEditError,
    insert_after_heading_html,
    replace_section_html,
)


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

    def test_insert_after_heading_html_inserts_immediately_after_heading(self) -> None:
        body_html = (
            "<h1>Guide</h1>"
            "<p>Intro</p>"
            "<h2>Install</h2>"
            "<p>Old install step</p>"
            "<h2>Usage</h2>"
            "<p>Run command</p>"
        )

        result = insert_after_heading_html(
            body_html,
            heading="Install",
            inserted_html="<p>New note</p><ul><li>Check this first</li></ul>",
        )

        self.assertEqual(result.matched_heading, "Install")
        self.assertEqual(result.heading_level, 2)
        self.assertIn("<p>New note</p>", result.inserted_html)
        self.assertIn("<ul><li>Check this first</li></ul>", result.updated_body_html)
        self.assertIn(
            "<h2>Install</h2><p>New note</p><ul><li>Check this first</li></ul><p>Old install step</p>",
            result.updated_body_html,
        )

    def test_insert_after_heading_html_fails_when_heading_missing(self) -> None:
        with self.assertRaises(SectionEditError):
            insert_after_heading_html(
                "<h1>Guide</h1><p>Body</p>",
                heading="Install",
                inserted_html="<p>Inserted</p>",
            )

    def test_insert_after_heading_html_fails_when_heading_ambiguous(self) -> None:
        with self.assertRaises(SectionEditError):
            insert_after_heading_html(
                "<h2>Install</h2><p>A</p><h2>Install</h2><p>B</p>",
                heading="Install",
                inserted_html="<p>Inserted</p>",
            )


_CODE_MACRO = (
    '<ac:structured-macro ac:name="code" ac:schema-version="1">'
    '<ac:parameter ac:name="language">text</ac:parameter>'
    "<ac:plain-text-body><![CDATA[Credit = Cost × E]]></ac:plain-text-body>"
    "</ac:structured-macro>"
)


class SectionEditCdataTests(unittest.TestCase):
    def test_replace_section_keeps_cdata_macro_body_outside_edited_section(self) -> None:
        body_html = (
            "<h2>Formula</h2>"
            + _CODE_MACRO
            + "<h2>Other</h2><p>old</p>"
        )

        result = replace_section_html(
            body_html,
            heading="Other",
            replacement_html="<p>new</p>",
        )

        self.assertIn("<![CDATA[Credit = Cost × E]]>", result.updated_body_html)
        self.assertIn("<p>new</p>", result.updated_body_html)
        self.assertNotIn("<p>old</p>", result.updated_body_html)

    def test_replace_section_keeps_cdata_in_replacement_and_in_replaced_section(self) -> None:
        old_macro = _CODE_MACRO.replace("Credit = Cost × E", "old formula")
        body_html = "<h2>Formula</h2>" + old_macro + "<h2>Other</h2><p>text</p>"

        result = replace_section_html(
            body_html,
            heading="Formula",
            replacement_html=_CODE_MACRO + "<p>note</p>",
        )

        self.assertIn("<![CDATA[old formula]]>", result.old_section_html)
        self.assertIn("<![CDATA[Credit = Cost × E]]>", result.new_section_html)
        self.assertIn("<![CDATA[Credit = Cost × E]]>", result.updated_body_html)
        self.assertNotIn("old formula", result.updated_body_html)

    def test_insert_after_heading_keeps_cdata_in_body_and_inserted_fragment(self) -> None:
        existing_macro = _CODE_MACRO.replace("Credit = Cost × E", "existing formula")
        body_html = "<h2>Formula</h2>" + existing_macro + "<h2>Other</h2><p>text</p>"

        result = insert_after_heading_html(
            body_html,
            heading="Other",
            inserted_html=_CODE_MACRO,
        )

        self.assertIn("<![CDATA[Credit = Cost × E]]>", result.inserted_html)
        self.assertIn("<![CDATA[existing formula]]>", result.updated_body_html)
        self.assertIn("<![CDATA[Credit = Cost × E]]>", result.updated_body_html)

    def test_multiple_cdata_sections_with_special_characters_are_restored_in_place(self) -> None:
        math_macro = (
            '<ac:structured-macro ac:name="mathblock" ac:schema-version="1">'
            "<ac:plain-text-body><![CDATA[\\text{Credit} = \\sum_{i} a_i < b & c]]></ac:plain-text-body>"
            "</ac:structured-macro>"
        )
        second_code = _CODE_MACRO.replace("Credit = Cost × E", "if (a < b && c) { run(); }")
        body_html = (
            "<h2>Formula</h2>" + _CODE_MACRO + math_macro
            + "<h2>Code</h2>" + second_code
            + "<h2>Other</h2><p>old</p>"
        )

        result = replace_section_html(
            body_html,
            heading="Other",
            replacement_html="<p>new</p>",
        )

        updated = result.updated_body_html
        expected_in_order = [
            "<![CDATA[Credit = Cost × E]]>",
            "<![CDATA[\\text{Credit} = \\sum_{i} a_i < b & c]]>",
            "<![CDATA[if (a < b && c) { run(); }]]>",
            "<h2>Other</h2><p>new</p>",
        ]
        positions = [updated.find(piece) for piece in expected_in_order]
        self.assertTrue(all(position >= 0 for position in positions), updated)
        self.assertEqual(positions, sorted(positions), updated)
        self.assertNotIn("conjira-cdata", updated)
