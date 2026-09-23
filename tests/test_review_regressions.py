"""Offline/synthetic regression expectations for conjira-cli 0.2.7.

These tests intentionally fail on the reviewed release. No real credentials or
Atlassian endpoints are used. Only the redirect test starts localhost servers.
Run: PYTHONPATH=<reviewed checkout>/src python3 reproduce_review_findings.py
"""

import io
import json
import tempfile
import threading
import unittest
import urllib.error
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from conjira_cli.cli import _build_parser, _handle_jira, _handle_confluence
from conjira_cli.client import (
    BaseAtlassianClient,
    ConfluenceClient,
    ConfluenceError,
    JiraClient,
)
from conjira_cli.config import ConfigError, ConfluenceSettings, JiraSettings
from conjira_cli.markdown_export import MarkdownExporter
from conjira_cli.markdown_import import markdown_to_storage_html
from conjira_cli.tree_export import export_page_tree

FAKE_TOKEN = "synthetic-review-token-not-a-real-credential"
OBSERVATIONS = {}


def macro_body(storage):
    root = ET.fromstring('<root xmlns:ac="urn:ac">' + storage + "</root>")
    return root.find(".//{urn:ac}plain-text-body").text


class ReviewRegressions(unittest.TestCase):
    def test_export_preserves_code_and_math_operators(self):
        source = 'value = price * count\npattern = "&lt;tag&gt;"'
        storage = (
            '<ac:structured-macro ac:name="code">'
            '<ac:parameter ac:name="language">python</ac:parameter>'
            "<ac:plain-text-body><![CDATA[" + source + "]]></ac:plain-text-body>"
            "</ac:structured-macro>"
        )
        exported = MarkdownExporter("https://wiki.example", "1").convert_fragment(
            storage
        )
        OBSERVATIONS["export_code"] = {"source": source, "exported": exported}
        self.assertIn(source, exported)

    def test_import_preserves_literal_html_inside_code(self):
        source = 'print("<br>")'
        storage = markdown_to_storage_html("```python\n" + source + "\n```")
        actual = macro_body(storage)
        OBSERVATIONS["import_code"] = {"source": source, "actual": actual}
        self.assertEqual(source, actual)

    def test_jira_extra_fields_cannot_override_allowed_project(self):
        settings = JiraSettings(
            base_url="https://jira.example",
            token=FAKE_TOKEN,
            allowed_project_keys={"DEMO"},
            rate_limit_enabled=False,
        )
        args = _build_parser().parse_args(
            [
                "jira-create-issue",
                "--allow-write",
                "--project-key",
                "DEMO",
                "--summary",
                "Synthetic issue",
                "--issue-type-name",
                "Task",
                "--fields-json",
                '{"project":{"key":"OTHER"}}',
            ]
        )
        with (
            mock.patch("conjira_cli.cli.build_jira_settings", return_value=settings),
            mock.patch.object(
                JiraClient, "request", return_value={"id": "42", "key": "OTHER-42"}
            ) as request,
        ):
            try:
                _handle_jira(args)
            except (
                ConfigError,
                __import__("conjira_cli.client", fromlist=["JiraError"]).JiraError,
            ):
                return
        actual = request.call_args.kwargs["body"]["fields"]["project"]["key"]
        OBSERVATIONS["jira_allowlist"] = {"allowed": ["DEMO"], "sent_project": actual}
        self.assertEqual(actual, "DEMO")

    def test_pagination_follows_next_after_server_caps_batch(self):
        client = ConfluenceClient(
            "https://wiki.example", FAKE_TOKEN, rate_limit_enabled=False
        )
        first = {
            "results": [{"id": "1"}, {"id": "2"}],
            "size": 2,
            "limit": 2,
            "_links": {"next": "/rest/api/content/0/child/page?start=2&limit=2"},
        }
        last = {"results": [{"id": "3"}], "size": 1, "limit": 2, "_links": {}}
        with (
            mock.patch.object(client, "request", return_value=last),
            mock.patch.object(
                client, "get_child_pages", side_effect=[first, last]
            ) as request,
        ):
            pages = client.list_child_pages("0", limit=200)
        OBSERVATIONS["pagination"] = {
            "expected_count": 3,
            "actual_count": len(pages),
            "requests": request.call_count,
        }
        self.assertEqual(len(pages), 3)

    def test_export_tree_does_not_overwrite_sanitized_title_collision(self):
        pages = {
            "0": {"id": "0", "title": "Root", "version": 1, "body_html": "<p>root</p>"},
            "1": {"id": "1", "title": "A/B", "version": 1, "body_html": "<p>first</p>"},
            "2": {
                "id": "2",
                "title": "A:B",
                "version": 1,
                "body_html": "<p>second</p>",
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            exported = export_page_tree(
                root_page=pages["0"],
                output_dir=Path(directory),
                fetch_page=pages.__getitem__,
                list_child_pages=lambda key: (
                    [pages["1"], pages["2"]] if key == "0" else []
                ),
                base_url="https://wiki.example",
            )
            paths = {item.output_file for item in exported}
            OBSERVATIONS["tree_collision"] = {
                "reported_count": len(exported),
                "actual_files": len(paths),
            }
            self.assertEqual(len(paths), len(exported))

    def test_auth_check_rejects_html_login_page(self):
        client = ConfluenceClient(
            "https://wiki.example", FAKE_TOKEN, rate_limit_enabled=False
        )
        with mock.patch.object(
            client, "request", return_value="<html><form>SSO Login</form></html>"
        ):
            try:
                result = client.auth_check()
            except ConfluenceError:
                return
        OBSERVATIONS["auth_html"] = result
        self.assertFalse(result["authenticated"])

    def test_retry_after_is_not_shortened(self):
        client = BaseAtlassianClient(
            "https://wiki.example", FAKE_TOKEN, rate_limit_enabled=False
        )
        error = urllib.error.HTTPError(
            "https://wiki.example",
            429,
            "rate limited",
            {"Retry-After": "120"},
            io.BytesIO(b"{}"),
        )
        actual = client._retry_delay_seconds(error, 1)
        OBSERVATIONS["retry_after"] = {
            "server_wait_seconds": 120,
            "client_wait_seconds": actual,
        }
        self.assertGreaterEqual(actual, 120)

    def test_refresh_does_not_switch_source_host_silently(self):
        settings = ConfluenceSettings(
            base_url="https://wiki-b.example",
            token=FAKE_TOKEN,
            rate_limit_enabled=False,
        )
        remote_page = {
            "id": "1",
            "type": "page",
            "title": "Different page",
            "version": {"number": 2},
            "space": {"key": "DOCS"},
            "body": {"storage": {"value": "<p>Different host content</p>"}},
            "_links": {"base": settings.base_url, "webui": "/pages/1"},
        }
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "note.md"
            initial = (
                "---\nconfluence_page_id: 1\nconfluence_version: 1\n"
                "source_url: https://wiki-a.example/pages/1\n---\nOriginal content\n"
            )
            file.write_text(initial)
            args = _build_parser().parse_args(["refresh-page-md", "--file", str(file)])
            with (
                mock.patch(
                    "conjira_cli.cli.build_confluence_settings", return_value=settings
                ),
                mock.patch.object(
                    ConfluenceClient, "get_page", return_value=remote_page
                ),
            ):
                try:
                    _handle_confluence(args)
                except ConfigError:
                    return
            OBSERVATIONS["refresh_host"] = {
                "original_host": "wiki-a.example",
                "new_host": settings.base_url,
                "original_preserved": file.read_text() == initial,
            }
            self.assertEqual(file.read_text(), initial)

    def test_cross_origin_redirect_does_not_forward_authorization(self):
        observed = []

        class Receiver(BaseHTTPRequestHandler):
            def do_GET(self):
                observed.append(bool(self.headers.get("Authorization")))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *_):
                pass

        receiver = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)

        class Redirector(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header(
                    "Location", f"http://localhost:{receiver.server_port}/sink"
                )
                self.end_headers()

            def log_message(self, *_):
                pass

        redirector = ThreadingHTTPServer(("127.0.0.1", 0), Redirector)
        threads = [
            threading.Thread(target=server.serve_forever, daemon=True)
            for server in (receiver, redirector)
        ]
        for thread in threads:
            thread.start()
        try:
            client = BaseAtlassianClient(
                f"http://127.0.0.1:{redirector.server_port}",
                FAKE_TOKEN,
                rate_limit_enabled=False,
                timeout_seconds=3,
            )
            try:
                client.request("GET", "/source")
            except Exception:
                pass  # Blocking the redirect is an acceptable safe behavior.
            OBSERVATIONS["redirect"] = {
                "authorization_reached_different_origin": any(observed)
            }
            self.assertFalse(any(observed))
        finally:
            for server in (redirector, receiver):
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join()


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ReviewRegressions)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    target = Path(__file__).with_name("observations.json")
    target.write_text(json.dumps(OBSERVATIONS, ensure_ascii=False, indent=2) + "\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
