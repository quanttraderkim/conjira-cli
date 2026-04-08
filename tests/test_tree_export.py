import tempfile
import unittest
from pathlib import Path

from conjira_cli.tree_export import export_page_tree, sanitize_path_component


class TreeExportTests(unittest.TestCase):
    def test_sanitize_path_component_replaces_invalid_chars(self) -> None:
        self.assertEqual(sanitize_path_component('A/B:C*D?'), 'A_B_C_D_')

    def test_export_page_tree_writes_nested_index_files(self) -> None:
        root_page = {
            "id": "1",
            "title": "Root Page",
            "version": 1,
            "webui_url": "https://confluence.example.com/pages/1",
            "body_html": "<p>Root body</p>",
            "ancestors": [],
        }
        child_page = {
            "id": "2",
            "title": "Child Page",
            "version": 2,
            "webui_url": "https://confluence.example.com/pages/2",
            "body_html": "<p>Child body</p>",
            "ancestors": [{"id": "1"}],
        }

        pages = {
            "1": root_page,
            "2": child_page,
        }
        children = {
            "1": [{"id": "2", "title": "Child Page"}],
            "2": [],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            exported = export_page_tree(
                root_page=root_page,
                output_dir=Path(tmp_dir),
                fetch_page=lambda page_id: pages[page_id],
                list_child_pages=lambda page_id: children[page_id],
                base_url="https://confluence.example.com",
            )

            root_index = Path(tmp_dir) / "Root Page" / "index.md"
            child_index = Path(tmp_dir) / "Root Page" / "Child Page" / "index.md"

            self.assertTrue(root_index.exists())
            self.assertTrue(child_index.exists())
            self.assertIn("confluence_page_id: 1", root_index.read_text(encoding="utf-8"))
            self.assertIn("confluence_page_id: 2", child_index.read_text(encoding="utf-8"))
            self.assertIn("confluence_parent_page_id: 1", child_index.read_text(encoding="utf-8"))
            self.assertEqual(len(exported), 2)
