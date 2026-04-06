import tempfile
import unittest
from pathlib import Path

from conjira_cli.cli import (
    _read_export_metadata,
    _resolve_export_output_path,
    _sanitize_markdown_filename,
)
from conjira_cli.config import ConfigError


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
