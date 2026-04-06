import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from conjira_cli.cli import (
    _handle_confluence,
    _handle_jira,
    _read_confluence_body_arg,
    _read_optional_confluence_body_arg,
    _read_export_metadata,
    _resolve_export_output_path,
    _sanitize_markdown_filename,
)
from conjira_cli.config import ConfigError, ConfluenceSettings, JiraSettings


class CliTests(unittest.TestCase):
    def test_sanitize_markdown_filename_replaces_invalid_chars(self) -> None:
        self.assertEqual(
            _sanitize_markdown_filename('A/B:C*D?'),
            'A_B_C_D_.md',
        )

    def test_resolve_export_output_path_uses_default_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _resolve_export_output_path(
                title="Demo Page",
                output_file=None,
                output_dir=None,
                filename=None,
                staging_local=False,
                default_dir=tmp_dir,
                staging_dir=None,
            )

        self.assertEqual(result, Path(tmp_dir) / "Demo Page.md")

    def test_resolve_export_output_path_uses_staging_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _resolve_export_output_path(
                title="Demo Page",
                output_file=None,
                output_dir=None,
                filename="custom.md",
                staging_local=True,
                default_dir=None,
                staging_dir=tmp_dir,
            )

        self.assertEqual(result, Path(tmp_dir) / "custom.md")

    def test_resolve_export_output_path_requires_target(self) -> None:
        with self.assertRaises(ConfigError):
            _resolve_export_output_path(
                title="Demo Page",
                output_file=None,
                output_dir=None,
                filename=None,
                staging_local=False,
                default_dir=None,
                staging_dir=None,
            )

    def test_read_export_metadata_extracts_page_id_and_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "page.md"
            path.write_text(
                "\n".join(
                    [
                        "---",
                        'title: "Demo Page"',
                        "confluence_page_id: 12345",
                        "confluence_version: 7",
                        "source_url: https://confluence.example.com/pages/12345",
                        "---",
                        "",
                        "# Demo Page",
                    ]
                ),
                encoding="utf-8",
            )

            metadata = _read_export_metadata(path)

        self.assertEqual(metadata["page_id"], "12345")
        self.assertEqual(metadata["local_version"], 7)
        self.assertEqual(metadata["source_url"], "https://confluence.example.com/pages/12345")

    def test_read_export_metadata_requires_page_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "page.md"
            path.write_text(
                "\n".join(
                    [
                        "---",
                        'title: "Demo Page"',
                        "---",
                        "",
                        "# Demo Page",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                _read_export_metadata(path)

    def test_read_confluence_body_arg_converts_markdown(self) -> None:
        result = _read_confluence_body_arg(
            raw_html=None,
            html_file=None,
            raw_markdown="# Demo\n\n- Item A",
            markdown_file=None,
        )

        self.assertIn("<h1>Demo</h1>", result)
        self.assertIn("<ul><li>Item A</li></ul>", result)

    def test_read_confluence_body_arg_reads_html_file_without_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "body.html"
            path.write_text("<p>Ready HTML</p>", encoding="utf-8")

            result = _read_confluence_body_arg(
                raw_html=None,
                html_file=str(path),
                raw_markdown=None,
                markdown_file=None,
            )

        self.assertEqual(result, "<p>Ready HTML</p>")

    def test_read_optional_confluence_body_arg_returns_none_when_missing(self) -> None:
        self.assertIsNone(
            _read_optional_confluence_body_arg(
                raw_html=None,
                html_file=None,
                raw_markdown=None,
                markdown_file=None,
            )
        )

    def test_handle_confluence_create_page_dry_run_returns_preview(self) -> None:
        args = SimpleNamespace(
            command="create-page",
            base_url=None,
            token=None,
            token_file=None,
            token_keychain_service=None,
            token_keychain_account=None,
            timeout=None,
            env_file=None,
            space_key="DOCS",
            parent_id="100001",
            title="Demo Page",
            allow_write=False,
            dry_run=True,
            body_html=None,
            body_file=None,
            body_markdown="# Demo\n\n- Item A",
            body_markdown_file=None,
        )
        settings = ConfluenceSettings(
            base_url="https://confluence.example.com",
            token="token",
            timeout_seconds=30,
        )

        with mock.patch("conjira_cli.cli.build_confluence_settings", return_value=settings):
            payload = _handle_confluence(args)

        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["action"], "create-page")
        self.assertEqual(payload["space_key"], "DOCS")
        self.assertEqual(payload["body_source"], "markdown")
        self.assertIn("Demo", payload["body_preview"])

    def test_handle_confluence_update_page_dry_run_uses_live_page_without_write(self) -> None:
        args = SimpleNamespace(
            command="update-page",
            base_url=None,
            token=None,
            token_file=None,
            token_keychain_service=None,
            token_keychain_account=None,
            timeout=None,
            env_file=None,
            page_id="12345",
            allow_write=False,
            dry_run=True,
            title="Updated Title",
            body_html=None,
            body_file=None,
            body_markdown=None,
            body_markdown_file=None,
            append_html=None,
            append_file=None,
            append_markdown="New paragraph",
            append_markdown_file=None,
        )
        settings = ConfluenceSettings(
            base_url="https://confluence.example.com",
            token="token",
            timeout_seconds=30,
        )
        page = {
            "id": "12345",
            "type": "page",
            "title": "Old Title",
            "space": {"key": "DOCS"},
            "version": {"number": 7},
            "body": {"storage": {"value": "<p>Existing body</p>"}},
            "_links": {
                "base": "https://confluence.example.com",
                "webui": "/pages/viewpage.action?pageId=12345",
            },
        }

        with mock.patch("conjira_cli.cli.build_confluence_settings", return_value=settings), mock.patch(
            "conjira_cli.cli.ConfluenceClient.get_page",
            return_value=page,
        ) as mock_get_page, mock.patch(
            "conjira_cli.cli.ConfluenceClient.update_page"
        ) as mock_update_page:
            payload = _handle_confluence(args)

        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["action"], "update-page")
        self.assertEqual(payload["page_id"], "12345")
        self.assertEqual(payload["next_title"], "Updated Title")
        self.assertTrue(payload["body_appended"])
        self.assertEqual(payload["append_source"], "markdown")
        mock_get_page.assert_called_once_with("12345", expand="body.storage,version,space")
        mock_update_page.assert_not_called()

    def test_handle_jira_add_comment_dry_run_returns_preview(self) -> None:
        args = SimpleNamespace(
            command="jira-add-comment",
            base_url=None,
            token=None,
            token_file=None,
            token_keychain_service=None,
            token_keychain_account=None,
            timeout=None,
            env_file=None,
            issue_key="DEMO-123",
            allow_write=False,
            dry_run=True,
            body="Preview comment body",
            body_file=None,
        )
        settings = JiraSettings(
            base_url="https://jira.example.com",
            token="token",
            timeout_seconds=30,
        )
        issue = {
            "id": "9000",
            "key": "DEMO-123",
            "fields": {
                "summary": "Demo issue",
                "status": {"name": "In Progress"},
                "issuetype": {"name": "Task"},
                "project": {"key": "DEMO"},
            },
        }

        with mock.patch("conjira_cli.cli.build_jira_settings", return_value=settings), mock.patch(
            "conjira_cli.cli.JiraClient.get_issue",
            return_value=issue,
        ) as mock_get_issue, mock.patch(
            "conjira_cli.cli.JiraClient.add_comment"
        ) as mock_add_comment:
            payload = _handle_jira(args)

        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["action"], "jira-add-comment")
        self.assertEqual(payload["issue_key"], "DEMO-123")
        self.assertEqual(payload["issue_status"], "In Progress")
        self.assertIn("Preview comment body", payload["comment_preview"])
        mock_get_issue.assert_called_once_with("DEMO-123")
        mock_add_comment.assert_not_called()

    def test_handle_confluence_upload_attachment_dry_run_detects_replace_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "chart.png"
            file_path.write_bytes(b"png-data")
            args = SimpleNamespace(
                command="upload-attachment",
                base_url=None,
                token=None,
                token_file=None,
                token_keychain_service=None,
                token_keychain_account=None,
                timeout=None,
                env_file=None,
                page_id="12345",
                file=str(file_path),
                comment="Refresh chart",
                allow_write=False,
                dry_run=True,
                major_edit=False,
            )
            settings = ConfluenceSettings(
                base_url="https://confluence.example.com",
                token="token",
                timeout_seconds=30,
            )
            attachments = {
                "results": [
                    {
                        "id": "att-1",
                        "title": "chart.png",
                        "metadata": {"mediaType": "image/png"},
                        "extensions": {"fileSize": 2048},
                    }
                ]
            }

            with mock.patch("conjira_cli.cli.build_confluence_settings", return_value=settings), mock.patch(
                "conjira_cli.cli.ConfluenceClient.get_attachments",
                return_value=attachments,
            ) as mock_get_attachments, mock.patch(
                "conjira_cli.cli.ConfluenceClient.upload_attachment"
            ) as mock_upload_attachment:
                payload = _handle_confluence(args)

        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["action"], "upload-attachment")
        self.assertEqual(payload["mode"], "replace")
        self.assertEqual(payload["file_name"], "chart.png")
        self.assertEqual(payload["comment"], "Refresh chart")
        mock_get_attachments.assert_called_once_with("12345")
        mock_upload_attachment.assert_not_called()

    def test_handle_jira_create_issue_dry_run_returns_preview(self) -> None:
        args = SimpleNamespace(
            command="jira-create-issue",
            base_url=None,
            token=None,
            token_file=None,
            token_keychain_service=None,
            token_keychain_account=None,
            timeout=None,
            env_file=None,
            project_key="DEMO",
            summary="Preview issue",
            issue_type_name="Task",
            allow_write=False,
            dry_run=True,
            description="Preview description",
            description_file=None,
            fields_json='{"priority": {"name": "High"}}',
            fields_file=None,
        )
        settings = JiraSettings(
            base_url="https://jira.example.com",
            token="token",
            timeout_seconds=30,
        )

        with mock.patch("conjira_cli.cli.build_jira_settings", return_value=settings), mock.patch(
            "conjira_cli.cli.JiraClient.create_issue"
        ) as mock_create_issue:
            payload = _handle_jira(args)

        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["action"], "jira-create-issue")
        self.assertEqual(payload["project_key"], "DEMO")
        self.assertEqual(payload["issue_type_name"], "Task")
        self.assertEqual(payload["extra_field_keys"], ["priority"])
        self.assertIn("/projects/DEMO", payload["project_browse_url"])
        mock_create_issue.assert_not_called()
