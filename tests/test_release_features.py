import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from conjira_cli.cli import _build_parser, _handle_confluence, _handle_jira
from conjira_cli.client import ConfluenceClient, ConfluenceError, JiraClient, JiraError
from conjira_cli.config import ConfluenceSettings, ConfigError, JiraSettings
from conjira_cli.diagnostics import doctor
from conjira_cli.files import metadata, stamp_export, validate_source, write_export
from conjira_cli.markdown_export import MarkdownExporter
from conjira_cli.markdown_import import markdown_to_storage_html
from conjira_cli.operations import batch_read, search_results
from conjira_cli.section_edit import list_headings, replace_section_html


PAGE = {
    "id": "1",
    "type": "page",
    "title": "Demo",
    "space": {"key": "DOCS"},
    "version": {"number": 7},
    "body": {"storage": {"value": "<h2>Plan</h2><p>Old</p>"}},
    "_links": {"base": "https://wiki.example", "webui": "/pages/1"},
}


class ReleaseFeatures(unittest.TestCase):
    def test_literal_export_import_roundtrip(self):
        import xml.etree.ElementTree as ET

        for code in [
            "value = a * b",
            'pattern = "&lt;x&gt;"',
            'print("<br>")',
            "before\n```\ninside\n```\nafter",
            "a\n\n\nb",
            "\nleading and trailing\n\n",
            "  x  \n    y\t",
        ]:
            with self.subTest(code=code):
                storage = markdown_to_storage_html("````python\n" + code + "\n````")
                md = MarkdownExporter("https://wiki.example", "1").convert_fragment(
                    storage
                )
                returned = markdown_to_storage_html(md)
                root = ET.fromstring('<r xmlns:ac="urn:ac">' + returned + "</r>")
                self.assertEqual(root.find(".//{urn:ac}plain-text-body").text, code)

    def test_nested_code_preserves_operators(self):
        code = '<ul><li><p>Example</p><ac:structured-macro ac:name="code"><ac:plain-text-body><![CDATA[x = a * b\n\n\nprint("&lt;x&gt;")]]></ac:plain-text-body></ac:structured-macro></li></ul>'
        md = MarkdownExporter("https://wiki.example", "1").convert_fragment(code)
        self.assertIn("x = a * b", md)
        self.assertIn("&lt;x&gt;", md)

    def test_strict_conversion_explains_loss(self):
        storage = '<ac:structured-macro ac:name="unknown"><ac:plain-text-body><![CDATA[source]]></ac:plain-text-body></ac:structured-macro>'
        exporter = MarkdownExporter("https://wiki.example", "1")
        self.assertIn("source", exporter.convert_fragment(storage))
        self.assertEqual(exporter.warnings[0]["code"], "unsupported_macro")
        with self.assertRaisesRegex(ValueError, "Strict conversion"):
            MarkdownExporter("https://wiki.example", "1", strict=True).convert_fragment(
                storage
            )

    def test_nested_heading_occurrences_target_only_selected_section(self):
        original = "<ac:layout><ac:layout-section><ac:layout-cell><h2>Plan</h2><p>A</p></ac:layout-cell><ac:layout-cell><h2>Plan</h2><p>B</p></ac:layout-cell></ac:layout-section></ac:layout>"
        self.assertEqual([h["occurrence"] for h in list_headings(original)], [1, 2])
        result = replace_section_html(
            original, heading="Plan", replacement_html="<p>New</p>", occurrence=2
        )
        self.assertIn("<p>A</p>", result.updated_body_html)
        self.assertIn("<p>New</p>", result.updated_body_html)
        self.assertNotIn("<p>B</p>", result.updated_body_html)

    def test_heading_occurrence_follows_document_order_across_containers(self):
        body = "<div><h2>Plan</h2><p>Nested first</p></div><h2>Plan</h2><p>Top-level second</p>"
        result = replace_section_html(
            body, heading="Plan", replacement_html="<p>Changed</p>", occurrence=1
        )
        self.assertNotIn("Nested first", result.updated_body_html)
        self.assertIn("Top-level second", result.updated_body_html)
        with self.assertRaises(ValueError):
            replace_section_html(
                body, heading="Plan", replacement_html="<p>Changed</p>", occurrence=0
            )

    def test_dry_run_diff_and_expected_version_guard(self):
        settings = ConfluenceSettings(
            "https://wiki.example", "fake", rate_limit_enabled=False
        )
        client = mock.Mock(spec=ConfluenceClient)
        client.get_page.return_value = PAGE
        client.summarize_page.side_effect = ConfluenceClient.summarize_page
        args = _build_parser().parse_args(
            [
                "replace-section",
                "--page-id",
                "1",
                "--heading",
                "Plan",
                "--section-html",
                "<p>New</p>",
                "--dry-run",
            ]
        )
        preview = _handle_confluence(args, settings=settings, client=client)
        self.assertEqual(preview["current_version"], 7)
        self.assertIn("<p>New</p>", preview["diff"])
        args.dry_run, args.allow_write, args.expected_version = False, True, 6
        with self.assertRaises(ConfluenceError) as caught:
            _handle_confluence(args, settings=settings, client=client)
        self.assertEqual(caught.exception.status_code, 409)
        client.update_page_from_snapshot.assert_not_called()

    def test_no_child_api_call_for_normal_page(self):
        settings = ConfluenceSettings(
            "https://wiki.example", "fake", rate_limit_enabled=False
        )
        client = mock.Mock(spec=ConfluenceClient)
        client.get_page.return_value = PAGE
        client.summarize_page.side_effect = ConfluenceClient.summarize_page
        args = _build_parser().parse_args(["get-page", "--page-id", "1"])
        _handle_confluence(args, settings=settings, client=client)
        client.get_page.assert_called_once()
        client.list_child_pages.assert_not_called()

    def test_export_with_explicit_filename_still_works(self):
        settings = ConfluenceSettings(
            "https://wiki.example", "fake", rate_limit_enabled=False
        )
        client = mock.Mock(spec=ConfluenceClient)
        client.get_page.return_value = PAGE
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.md"
            args = _build_parser().parse_args(
                ["export-page-md", "--page-id", "1", "--output-file", str(path)]
            )
            result = _handle_confluence(args, settings=settings, client=client)
            self.assertTrue(path.exists())
            self.assertEqual(result["output_file"], str(path))

    def test_space_allowlist_applies_to_updates(self):
        settings = ConfluenceSettings(
            "https://wiki.example", "fake", allowed_space_keys={"OTHER"}
        )
        client = mock.Mock(spec=ConfluenceClient)
        client.get_page.return_value = PAGE
        args = _build_parser().parse_args(
            ["update-page", "--page-id", "1", "--title", "New", "--allow-write"]
        )
        with self.assertRaisesRegex(ConfigError, "page space"):
            _handle_confluence(args, settings=settings, client=client)
        client.update_page_from_snapshot.assert_not_called()

    def test_export_refuses_local_edits_and_force_keeps_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.md"
            old = stamp_export(
                "---\nconfluence_page_id: 1\n---\nOriginal", "https://wiki.example"
            )
            write_export(path, old, page_id="1", base_url="https://wiki.example")
            path.write_text(old + "\nLocal change")
            with self.assertRaises(ConfigError):
                write_export(path, old, page_id="1", base_url="https://wiki.example")
            backup = write_export(
                path, old, page_id="1", base_url="https://wiki.example", force=True
            )
            self.assertIn("Local change", Path(backup).read_text())
            self.assertEqual(path.read_text(), old)

    def test_force_cannot_overwrite_different_page_or_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.md"
            old = stamp_export(
                "---\nconfluence_page_id: 1\n---\nOriginal", "https://wiki.example/a"
            )
            path.write_text(old)
            with self.assertRaises(ConfigError):
                write_export(
                    path,
                    old,
                    page_id="2",
                    base_url="https://wiki.example/a",
                    force=True,
                )
            with self.assertRaises(ConfigError):
                validate_source(metadata(old), "https://wiki.example/b")

    def test_batch_has_bounded_parallelism_and_partial_errors(self):
        def fetch(key):
            if key == "bad":
                raise ValueError("Missing")
            return key

        result = batch_read("a,bad,a,b", fetch, workers=2)
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["results"][2]["data"], "b")

    def test_search_all_follows_server_limit_and_reports_remaining(self):
        client = mock.Mock(spec=JiraClient)
        client.search.side_effect = [
            {"issues": [{"id": "1"}, {"id": "2"}], "total": 5},
            {"issues": [{"id": "3"}], "total": 5},
        ]
        client.summarize_search_results.side_effect = lambda rows: {"results": rows}
        args = _build_parser().parse_args(
            ["jira-search", "--jql", "project = DEMO", "--all", "--max-items", "3"]
        )
        result = search_results(args, client, jira=True)
        self.assertEqual(result["count"], 3)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["next_start"], 3)
        self.assertEqual(client.search.call_args.kwargs["start"], 2)

    def test_jira_extra_fields_preview_rejects_reserved_fields(self):
        settings = JiraSettings(
            "https://jira.example", "fake", allowed_project_keys={"DEMO"}
        )
        args = _build_parser().parse_args(
            [
                "jira-create-issue",
                "--dry-run",
                "--project-key",
                "DEMO",
                "--summary",
                "Test",
                "--issue-type-name",
                "Task",
                "--fields-json",
                '{"project":{"key":"OTHER"}}',
            ]
        )
        with self.assertRaises(JiraError):
            _handle_jira(
                args,
                settings=settings,
                client=JiraClient("https://jira.example", "fake"),
            )

    def test_write_5xx_is_not_retried_but_read_is(self):
        client = ConfluenceClient(
            "https://wiki.example", "fake", rate_limit_enabled=False, max_retries=1
        )
        error = urllib.error.HTTPError(
            "https://wiki.example", 503, "temporary", {}, io.BytesIO(b"{}")
        )
        self.assertFalse(client._should_retry_http_error(error, 1, "POST"))
        self.assertTrue(client._should_retry_http_error(error, 1, "GET"))

    def test_jira_update_and_transition_preview_share_write_guards(self):
        settings = JiraSettings(
            "https://jira.example",
            "fake",
            allowed_project_keys={"DEMO"},
            allowed_issue_keys={"DEMO-1"},
        )
        client = mock.Mock(spec=JiraClient)
        client.get_issue.return_value = {
            "key": "DEMO-1",
            "fields": {"project": {"key": "DEMO"}},
        }
        args = _build_parser().parse_args(
            [
                "jira-update-issue",
                "--issue-key",
                "DEMO-1",
                "--fields-json",
                '{"summary":"Changed"}',
                "--dry-run",
            ]
        )
        result = _handle_jira(args, settings=settings, client=client)
        self.assertTrue(result["dry_run"])
        client.request.assert_not_called()
        args.dry_run, args.allow_write = False, True
        _handle_jira(args, settings=settings, client=client)
        self.assertEqual(client.request.call_args.args[0], "PUT")
        client.request.reset_mock()
        client.request.return_value = {"transitions": [{"id": "31", "name": "Done"}]}
        args = _build_parser().parse_args(
            [
                "jira-transition-issue",
                "--issue-key",
                "DEMO-1",
                "--transition-id",
                "31",
                "--dry-run",
            ]
        )
        result = _handle_jira(args, settings=settings, client=client)
        self.assertEqual(result["request"]["transition"]["id"], "31")
        self.assertEqual(client.request.call_args.args[0], "GET")
        args.transition_id = "999"
        with self.assertRaises(ConfigError):
            _handle_jira(args, settings=settings, client=client)

    def test_expanded_tree_export_does_not_refetch_child_body(self):
        from conjira_cli.tree_export import export_page_tree

        root = {"id": "1", "title": "Root", "version": 1, "body_html": "<p>Root</p>"}
        child = {"id": "2", "title": "Child", "version": 1, "body_html": "<p>Child</p>"}
        fetch = mock.Mock(side_effect=AssertionError("Redundant page fetch"))
        with tempfile.TemporaryDirectory() as tmp:
            exported = export_page_tree(
                root_page=root,
                output_dir=Path(tmp),
                fetch_page=fetch,
                list_child_pages=lambda key: [child] if key == "1" else [],
                base_url="https://wiki.example",
            )
            self.assertEqual(len(exported), 2)
        fetch.assert_not_called()

    def test_attachment_pagination_follows_next_link(self):
        client = ConfluenceClient(
            "https://wiki.example/confluence", "fake", rate_limit_enabled=False
        )
        with mock.patch.object(
            client,
            "request",
            side_effect=[
                {
                    "results": [{"id": "1"}],
                    "_links": {
                        "next": "/confluence/rest/api/content/1/child/attachment?start=1"
                    },
                },
                {"results": [{"id": "2"}], "_links": {}},
            ],
        ) as request:
            result = client.get_attachments("1")
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(
            request.call_args.args[1], "/rest/api/content/1/child/attachment?start=1"
        )

    def test_redirect_allows_same_origin_but_blocks_downgrade(self):
        import urllib.request
        from conjira_cli.client import SafeRedirectHandler

        request = urllib.request.Request(
            "https://wiki.example/rest/a", headers={"Authorization": "Bearer synthetic"}
        )
        handler = SafeRedirectHandler()
        redirected = handler.redirect_request(
            request, mock.Mock(), 302, "Moved", {}, "https://wiki.example/rest/b"
        )
        self.assertEqual(redirected.get_header("Authorization"), "Bearer synthetic")
        with self.assertRaises(urllib.error.URLError):
            handler.redirect_request(
                request, mock.Mock(), 302, "Moved", {}, "http://wiki.example/rest/b"
            )

    def test_doctor_does_not_read_or_print_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "agent.env"
            config.write_text(
                "CONFLUENCE_BASE_URL=https://wiki.example\nCONFLUENCE_PAT=synthetic-secret\n"
            )
            with (
                mock.patch.dict("os.environ", {}, clear=True),
                mock.patch("conjira_cli.config._read_token_from_keychain") as read,
            ):
                result = doctor(str(config))
            read.assert_not_called()
            self.assertNotIn("synthetic-secret", json.dumps(result))
            self.assertTrue(result["products"]["confluence"]["configured"])

    def test_invalid_identifiers_cannot_change_request_paths(self):
        parser = _build_parser()
        with (
            mock.patch("sys.stderr", new_callable=io.StringIO),
            self.assertRaises(SystemExit),
        ):
            parser.parse_args(["get-page", "--page-id", "1/../../space"])
