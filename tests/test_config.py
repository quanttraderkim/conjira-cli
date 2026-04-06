import tempfile
import unittest
from pathlib import Path
from unittest import mock

from conjira_cli.config import build_jira_settings, build_settings, load_env_file


class ConfigTests(unittest.TestCase):
    def test_load_env_file_parses_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = Path(tmp_dir) / ".env"
            env_path.write_text(
                'CONFLUENCE_BASE_URL="https://example.com"\nCONFLUENCE_PAT=\'secret\'\n',
                encoding="utf-8",
            )
            data = load_env_file(env_path)

        self.assertEqual(data["CONFLUENCE_BASE_URL"], "https://example.com")
        self.assertEqual(data["CONFLUENCE_PAT"], "secret")

    def test_build_settings_uses_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = Path(tmp_dir) / ".env"
            env_path.write_text(
                "CONFLUENCE_BASE_URL=https://example.com\n"
                "CONFLUENCE_PAT=token\n"
                "CONFLUENCE_TIMEOUT_SECONDS=45\n"
                "CONFLUENCE_EXPORT_DEFAULT_DIR=/vault/inbox\n"
                "CONFLUENCE_EXPORT_STAGING_DIR=/tmp/staging\n",
                encoding="utf-8",
            )
            settings = build_settings(
                base_url=None,
                token=None,
                token_file=None,
                token_keychain_service=None,
                token_keychain_account=None,
                timeout_seconds=None,
                env_file=str(env_path),
            )

        self.assertEqual(settings.base_url, "https://example.com")
        self.assertEqual(settings.token, "token")
        self.assertEqual(settings.timeout_seconds, 45)
        self.assertEqual(settings.export_default_dir, "/vault/inbox")
        self.assertEqual(settings.export_staging_dir, "/tmp/staging")

    def test_build_settings_uses_token_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            token_path = Path(tmp_dir) / "token.txt"
            token_path.write_text("file-token\n", encoding="utf-8")
            settings = build_settings(
                base_url="https://example.com",
                token=None,
                token_file=str(token_path),
                token_keychain_service=None,
                token_keychain_account=None,
                timeout_seconds=30,
                env_file=None,
            )

        self.assertEqual(settings.token, "file-token")

    @mock.patch("conjira_cli.config.subprocess.run")
    def test_build_settings_uses_keychain(self, mock_run: mock.Mock) -> None:
        mock_run.return_value.stdout = "keychain-token\n"
        settings = build_settings(
            base_url="https://example.com",
            token=None,
            token_file=None,
            token_keychain_service="svc",
            token_keychain_account="acct",
            timeout_seconds=30,
            env_file=None,
        )

        self.assertEqual(settings.token, "keychain-token")

    def test_build_jira_settings_uses_jira_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = Path(tmp_dir) / ".env"
            env_path.write_text(
                "JIRA_BASE_URL=https://jira.example.com\n"
                "JIRA_PAT=jira-token\n"
                "JIRA_TIMEOUT_SECONDS=55\n"
                "JIRA_ALLOWED_PROJECT_KEYS=TEST,OPS\n"
                "JIRA_ALLOWED_ISSUE_KEYS=TEST-1,OPS-2\n",
                encoding="utf-8",
            )
            settings = build_jira_settings(
                base_url=None,
                token=None,
                token_file=None,
                token_keychain_service=None,
                token_keychain_account=None,
                timeout_seconds=None,
                env_file=str(env_path),
            )

        self.assertEqual(settings.base_url, "https://jira.example.com")
        self.assertEqual(settings.token, "jira-token")
        self.assertEqual(settings.timeout_seconds, 55)
        self.assertEqual(settings.allowed_project_keys, {"TEST", "OPS"})
        self.assertEqual(settings.allowed_issue_keys, {"TEST-1", "OPS-2"})
