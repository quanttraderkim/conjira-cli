import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from conjira_cli.cli import (
    _build_error_payload,
    _handle_confluence,
    _handle_jira,
    _read_confluence_body_arg,
    _read_optional_confluence_body_arg,
    _read_export_metadata,
    _resolve_export_output_path,
    _sanitize_markdown_filename,
)
from conjira_cli.config import ConfigError, ConfluenceSettings, JiraSettings
from conjira_cli.client import ConfluenceError, JiraError


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

    def test_handle_confluence_replace_section_dry_run_returns_preview(self) -> None:
        args = SimpleNamespace(
            command="replace-section",
            base_url=None,
            token=None,
            token_file=None,
            token_keychain_service=None,
            token_keychain_account=None,
            timeout=None,
            env_file=None,
            page_id="12345",
            heading="Install",
            allow_write=False,
            dry_run=True,
            section_html=None,
            section_file=None,
            section_markdown="Updated install section",
            section_markdown_file=None,
        )
        settings = ConfluenceSettings(
            base_url="https://confluence.example.com",
            token="token",
            timeout_seconds=30,
        )
        page = {
            "id": "12345",
            "type": "page",
            "title": "Guide",
            "space": {"key": "DOCS"},
            "version": {"number": 7},
            "body": {
                "storage": {
                    "value": (
                        "<h1>Guide</h1>"
                        "<h2>Install</h2>"
                        "<p>Old step</p>"
                        "<h2>Usage</h2>"
                        "<p>Run command</p>"
                    )
                }
            },
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
        self.assertEqual(payload["action"], "replace-section")
        self.assertEqual(payload["page_id"], "12345")
        self.assertEqual(payload["heading"], "Install")
        self.assertEqual(payload["matched_heading"], "Install")
        self.assertEqual(payload["body_source"], "markdown")
        self.assertIn("Old step", payload["old_section_preview"])
        self.assertIn("Updated install section", payload["new_section_preview"])
        mock_get_page.assert_called_once_with("12345", expand="body.storage,version,space")
        mock_update_page.assert_not_called()

    def test_handle_confluence_replace_section_write_updates_page(self) -> None:
        args = SimpleNamespace(
            command="replace-section",
            base_url=None,
            token=None,
            token_file=None,
            token_keychain_service=None,
            token_keychain_account=None,
            timeout=None,
            env_file=None,
            page_id="12345",
            heading="Install",
            allow_write=True,
            dry_run=False,
            section_html="<p>Replacement</p>",
            section_file=None,
            section_markdown=None,
            section_markdown_file=None,
        )
        settings = ConfluenceSettings(
            base_url="https://confluence.example.com",
            token="token",
            timeout_seconds=30,
        )
        page = {
            "id": "12345",
            "type": "page",
            "title": "Guide",
            "space": {"key": "DOCS"},
            "version": {"number": 7},
            "body": {
                "storage": {
                    "value": "<h2>Install</h2><p>Old step</p><h2>Usage</h2><p>Run command</p>"
                }
            },
            "_links": {
                "base": "https://confluence.example.com",
                "webui": "/pages/viewpage.action?pageId=12345",
            },
        }
        updated_summary = {
            "id": "12345",
            "type": "page",
            "status": "current",
            "title": "Guide",
            "space": {"key": "DOCS"},
            "version": {"number": 8},
            "_links": {
                "base": "https://confluence.example.com",
                "webui": "/pages/viewpage.action?pageId=12345",
            },
        }

        with mock.patch("conjira_cli.cli.build_confluence_settings", return_value=settings), mock.patch(
            "conjira_cli.cli.ConfluenceClient.get_page",
            return_value=page,
        ) as mock_get_page, mock.patch(
            "conjira_cli.cli.ConfluenceClient.update_page_from_snapshot",
            return_value=updated_summary,
        ) as mock_update_page:
            payload = _handle_confluence(args)

        self.assertEqual(payload["action"], "replace-section")
        self.assertEqual(payload["heading"], "Install")
        self.assertEqual(payload["matched_heading"], "Install")
        mock_get_page.assert_called_once_with("12345", expand="body.storage,version,space")
        mock_update_page.assert_called_once()
        self.assertEqual(mock_update_page.call_args.args[0]["id"], "12345")
        self.assertIn("<p>Replacement</p>", mock_update_page.call_args.kwargs["new_body_html"])

    def test_handle_confluence_move_page_dry_run_returns_preview(self) -> None:
        args = SimpleNamespace(
            command="move-page",
            base_url=None,
            token=None,
            token_file=None,
            token_keychain_service=None,
            token_keychain_account=None,
            timeout=None,
            env_file=None,
            page_id="12345",
            new_parent_id="99999",
            allow_write=False,
            dry_run=True,
        )
        settings = ConfluenceSettings(
            base_url="https://confluence.example.com",
            token="token",
            timeout_seconds=30,
        )
        page = {
            "id": "12345",
            "type": "page",
            "title": "Guide",
            "space": {"key": "DOCS"},
            "version": {"number": 7},
            "ancestors": [{"id": "10000"}],
            "body": {"storage": {"value": "<p>Body</p>"}},
            "_links": {
                "base": "https://confluence.example.com",
                "webui": "/pages/viewpage.action?pageId=12345",
            },
        }

        with mock.patch("conjira_cli.cli.build_confluence_settings", return_value=settings), mock.patch(
            "conjira_cli.cli.ConfluenceClient.get_page",
            return_value=page,
        ) as mock_get_page, mock.patch(
            "conjira_cli.cli.ConfluenceClient.update_page_from_snapshot"
        ) as mock_update_page:
            payload = _handle_confluence(args)

        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["action"], "move-page")
        self.assertEqual(payload["page_id"], "12345")
        self.assertEqual(payload["current_parent_id"], "10000")
        self.assertEqual(payload["new_parent_id"], "99999")
        mock_get_page.assert_called_once_with("12345", expand="body.storage,version,space,ancestors")
        mock_update_page.assert_not_called()

    def test_handle_confluence_move_page_write_updates_parent(self) -> None:
        args = SimpleNamespace(
            command="move-page",
            base_url=None,
            token=None,
            token_file=None,
            token_keychain_service=None,
            token_keychain_account=None,
            timeout=None,
            env_file=None,
            page_id="12345",
            new_parent_id="99999",
            allow_write=True,
            dry_run=False,
        )
        settings = ConfluenceSettings(
            base_url="https://confluence.example.com",
            token="token",
            timeout_seconds=30,
        )
        page = {
            "id": "12345",
            "type": "page",
            "title": "Guide",
            "space": {"key": "DOCS"},
            "version": {"number": 7},
            "ancestors": [{"id": "10000"}],
            "body": {"storage": {"value": "<p>Body</p>"}},
            "_links": {
                "base": "https://confluence.example.com",
                "webui": "/pages/viewpage.action?pageId=12345",
            },
        }
        updated_summary = {
            "id": "12345",
            "type": "page",
            "status": "current",
            "title": "Guide",
            "space": {"key": "DOCS"},
            "version": {"number": 8},
            "_links": {
                "base": "https://confluence.example.com",
                "webui": "/pages/viewpage.action?pageId=12345",
            },
        }

        with mock.patch("conjira_cli.cli.build_confluence_settings", return_value=settings), mock.patch(
            "conjira_cli.cli.ConfluenceClient.get_page",
            return_value=page,
        ) as mock_get_page, mock.patch(
            "conjira_cli.cli.ConfluenceClient.update_page_from_snapshot",
            return_value=updated_summary,
        ) as mock_update_page:
            payload = _handle_confluence(args)

        self.assertEqual(payload["action"], "move-page")
        self.assertEqual(payload["previous_parent_id"], "10000")
        self.assertEqual(payload["new_parent_id"], "99999")
        mock_get_page.assert_called_once_with("12345", expand="body.storage,version,space,ancestors")
        mock_update_page.assert_called_once()
        self.assertEqual(mock_update_page.call_args.args[0]["id"], "12345")
        self.assertEqual(mock_update_page.call_args.kwargs["new_parent_id"], "99999")

    def test_build_error_payload_adds_replace_section_guidance(self) -> None:
        payload = _build_error_payload(
            ConfigError('replace-section target heading "Install" was not found.')
        )

        self.assertEqual(payload["error_type"], "ConfigError")
        self.assertTrue(any("heading" in item.lower() for item in payload["guidance"]))

    def test_build_error_payload_adds_move_page_guidance(self) -> None:
        payload = _build_error_payload(
            ConfigError("move-page requires different current and new parent IDs.")
        )

        self.assertEqual(payload["error_type"], "ConfigError")
        self.assertTrue(any("different parent" in item.lower() for item in payload["guidance"]))

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

    def test_build_error_payload_adds_401_guidance(self) -> None:
        payload = _build_error_payload(
            ConfluenceError(
                "Unauthorized",
                status_code=401,
                payload={"message": "Unauthorized"},
            )
        )

        self.assertEqual(payload["status_code"], 401)
        self.assertEqual(payload["error_type"], "ConfluenceError")
        self.assertIn("guidance", payload)
        self.assertTrue(
            any("PAT" in item or "base-url" in item or "BASE_URL" in item for item in payload["guidance"])
        )

    def test_build_error_payload_adds_allowlist_guidance_for_config_error(self) -> None:
        payload = _build_error_payload(
            ConfigError("Write blocked: project key DEMO is not in JIRA_ALLOWED_PROJECT_KEYS.")
        )

        self.assertEqual(payload["error_type"], "ConfigError")
        self.assertIn("guidance", payload)
        self.assertTrue(any("allowlist" in item.lower() or "allowed" in item.lower() for item in payload["guidance"]))

    def test_build_error_payload_adds_404_guidance_for_jira(self) -> None:
        payload = _build_error_payload(
            JiraError(
                "Not found",
                status_code=404,
                payload={"errorMessages": ["Issue does not exist"]},
            )
        )

        self.assertEqual(payload["status_code"], 404)
        self.assertEqual(payload["error_type"], "JiraError")
        self.assertTrue(any("identifier" in item.lower() or "issue key" in item.lower() for item in payload["guidance"]))
