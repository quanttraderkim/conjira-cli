import unittest
from unittest import mock

from conjira_cli.client import ConfluenceClient, JiraClient


class _FakeHTTPResponse:
    def __init__(self, body: str, *, content_type: str) -> None:
        self._body = body.encode("utf-8")
        self.headers = {"Content-Type": content_type}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class ClientTests(unittest.TestCase):
    def test_update_page_from_snapshot_uses_snapshot_version_and_id(self) -> None:
        client = ConfluenceClient(base_url="https://confluence.example.com", token="token")
        snapshot = {
            "id": "123",
            "type": "page",
            "title": "Demo",
            "space": {"key": "TEST"},
            "version": {"number": 7},
            "body": {"storage": {"value": "<p>Old body</p>"}},
        }

        with mock.patch.object(client, "request", return_value={"id": "123"}) as mock_request:
            client.update_page_from_snapshot(
                snapshot,
                new_body_html="<p>New body</p>",
            )

        mock_request.assert_called_once()
        self.assertEqual(mock_request.call_args.args[0], "PUT")
        self.assertEqual(mock_request.call_args.args[1], "/rest/api/content/123")
        payload = mock_request.call_args.kwargs["body"]
        self.assertEqual(payload["version"]["number"], 8)
        self.assertEqual(payload["body"]["storage"]["value"], "<p>New body</p>")

    def test_update_page_from_snapshot_can_change_parent(self) -> None:
        client = ConfluenceClient(base_url="https://confluence.example.com", token="token")
        snapshot = {
            "id": "123",
            "type": "page",
            "title": "Demo",
            "space": {"key": "TEST"},
            "version": {"number": 7},
            "body": {"storage": {"value": "<p>Old body</p>"}},
        }

        with mock.patch.object(client, "request", return_value={"id": "123"}) as mock_request:
            client.update_page_from_snapshot(
                snapshot,
                new_parent_id="900",
            )

        payload = mock_request.call_args.kwargs["body"]
        self.assertEqual(payload["ancestors"], [{"id": "900"}])
        self.assertEqual(payload["version"]["number"], 8)

    def test_summarize_page_extracts_core_fields(self) -> None:
        page = {
            "id": "123",
            "type": "page",
            "status": "current",
            "title": "Demo",
            "space": {"key": "TEST"},
            "version": {"number": 7},
            "_links": {
                "base": "https://example.com",
                "webui": "/spaces/TEST/pages/123/Demo",
            },
        }

        summary = ConfluenceClient.summarize_page(page)

        self.assertEqual(summary["id"], "123")
        self.assertEqual(summary["space_key"], "TEST")
        self.assertEqual(summary["version"], 7)
        self.assertEqual(
            summary["webui_url"],
            "https://example.com/spaces/TEST/pages/123/Demo",
        )

    def test_summarize_attachment_extracts_core_fields(self) -> None:
        attachment = {
            "id": "att-1",
            "title": "chart.png",
            "metadata": {"mediaType": "image/png"},
            "extensions": {"fileSize": 2048},
            "_links": {
                "base": "https://example.com",
                "download": "/download/attachments/123/chart.png",
            },
        }

        summary = ConfluenceClient.summarize_attachment(attachment)

        self.assertEqual(summary["id"], "att-1")
        self.assertEqual(summary["title"], "chart.png")
        self.assertEqual(summary["media_type"], "image/png")
        self.assertEqual(summary["file_size"], 2048)
        self.assertEqual(
            summary["download_url"],
            "https://example.com/download/attachments/123/chart.png",
        )

    def test_summarize_issue_extracts_core_fields(self) -> None:
        client = JiraClient(base_url="https://jira.example.com", token="token")
        issue = {
            "id": "456",
            "key": "TEST-9",
            "fields": {
                "summary": "Demo issue",
                "status": {"name": "In Progress"},
                "issuetype": {"name": "Task"},
                "project": {"key": "TEST"},
                "assignee": {"displayName": "Assignee User"},
                "reporter": {"displayName": "Reporter User"},
                "updated": "2026-04-09T18:20:00.000+0900",
            },
        }

        summary = client.summarize_issue(issue)

        self.assertEqual(summary["key"], "TEST-9")
        self.assertEqual(summary["status"], "In Progress")
        self.assertEqual(summary["issue_type"], "Task")
        self.assertEqual(summary["updated"], "2026-04-09T18:20:00.000+0900")
        self.assertEqual(summary["browse_url"], "https://jira.example.com/browse/TEST-9")

    def test_summarize_issue_can_include_recent_comments(self) -> None:
        client = JiraClient(base_url="https://jira.example.com", token="token")
        issue = {
            "id": "456",
            "key": "TEST-9",
            "fields": {
                "summary": "Demo issue",
                "status": {"name": "In Progress"},
                "issuetype": {"name": "Task"},
                "project": {"key": "TEST"},
                "updated": "2026-04-09T18:20:00.000+0900",
                "comment": {
                    "total": 2,
                    "comments": [
                        {
                            "id": "1001",
                            "author": {"displayName": "Alex"},
                            "created": "2026-04-08T10:00:00.000+0900",
                            "updated": "2026-04-08T10:00:00.000+0900",
                            "body": "First comment",
                        },
                        {
                            "id": "1002",
                            "author": {"displayName": "Taylor"},
                            "created": "2026-04-09T09:00:00.000+0900",
                            "updated": "2026-04-09T09:10:00.000+0900",
                            "body": "Second comment with a longer body that should still remain readable.",
                        },
                    ],
                },
            },
        }

        summary = client.summarize_issue(issue, include_comments=True, comments_limit=1)

        self.assertEqual(summary["comment_count"], 2)
        self.assertEqual(len(summary["recent_comments"]), 1)
        self.assertEqual(summary["recent_comments"][0]["id"], "1002")
        self.assertEqual(summary["recent_comments"][0]["author"], "Taylor")

    def test_list_inline_comments_fetches_all_pages(self) -> None:
        client = ConfluenceClient(base_url="https://confluence.example.com", token="token")

        with mock.patch.object(
            client,
            "get_inline_comments",
            side_effect=[
                {"results": [{"id": "1"}, {"id": "2"}]},
                {"results": [{"id": "3"}]},
            ],
        ) as mock_get_inline_comments:
            comments = client.list_inline_comments("123", limit=2)

        self.assertEqual([comment["id"] for comment in comments], ["1", "2", "3"])
        self.assertEqual(mock_get_inline_comments.call_count, 2)

    def test_list_child_pages_fetches_all_pages(self) -> None:
        client = ConfluenceClient(base_url="https://confluence.example.com", token="token")

        with mock.patch.object(
            client,
            "get_child_pages",
            side_effect=[
                {"results": [{"id": "1"}, {"id": "2"}]},
                {"results": [{"id": "3"}]},
            ],
        ) as mock_get_child_pages:
            pages = client.list_child_pages("123", limit=2)

        self.assertEqual([page["id"] for page in pages], ["1", "2", "3"])
        self.assertEqual(mock_get_child_pages.call_count, 2)

class ValidateStorageHtmlTests(unittest.TestCase):
    def test_valid_xhtml_passes(self) -> None:
        from conjira_cli.client import validate_storage_html

        # Should not raise
        validate_storage_html("<p>Hello <strong>world</strong></p>")

    def test_invalid_xhtml_raises(self) -> None:
        from conjira_cli.client import validate_storage_html, ConfluenceError

        with self.assertRaises(ConfluenceError) as ctx:
            validate_storage_html("<p>Unclosed paragraph")
        self.assertIn("well-formed XHTML", str(ctx.exception))

    def test_bare_br_is_invalid(self) -> None:
        from conjira_cli.client import validate_storage_html, ConfluenceError

        with self.assertRaises(ConfluenceError):
            validate_storage_html("<p>line<br>break</p>")

    def test_valid_xhtml_with_confluence_macros_passes(self) -> None:
        from conjira_cli.client import validate_storage_html

        validate_storage_html(
            '<ac:structured-macro ac:name="code" ac:schema-version="1">'
            '<ac:parameter ac:name="language">python</ac:parameter>'
            '<ac:plain-text-body><![CDATA[print("hi")]]></ac:plain-text-body>'
            "</ac:structured-macro>"
        )

    def test_valid_xhtml_with_atlassian_namespace_passes(self) -> None:
        from conjira_cli.client import validate_storage_html

        validate_storage_html(
            '<td atlassian:data-highlight-colour="blue">text</td>'
        )

    def test_get_page_parses_json_even_when_content_type_is_not_json(self) -> None:
        client = ConfluenceClient(base_url="https://confluence.example.com", token="token")
        body = (
            '{"id":"123","type":"page","status":"current","title":"Demo",'
            '"space":{"key":"TEST"},"version":{"number":7}}'
        )

        with mock.patch(
            "conjira_cli.client.urllib.request.urlopen",
            return_value=_FakeHTTPResponse(body, content_type="text/plain; charset=utf-8"),
        ):
            page = client.get_page("123")

        self.assertEqual(page["id"], "123")
        self.assertEqual(ConfluenceClient.summarize_page(page)["title"], "Demo")

    def test_jira_auth_check_parses_json_even_when_content_type_is_not_json(self) -> None:
        client = JiraClient(base_url="https://jira.example.com", token="token")
        body = '{"version":"10.3.16","buildNumber":10030016,"deploymentType":"Server"}'

        with mock.patch(
            "conjira_cli.client.urllib.request.urlopen",
            return_value=_FakeHTTPResponse(body, content_type="text/plain; charset=utf-8"),
        ):
            payload = client.auth_check()

        self.assertEqual(payload["version"], "10.3.16")
        self.assertEqual(payload["build_number"], 10030016)
