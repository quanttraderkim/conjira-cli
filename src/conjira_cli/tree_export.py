from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from conjira_cli.markdown_export import MarkdownExporter


def sanitize_path_component(value: str) -> str:
    sanitized = "".join(
        "_" if char in '<>:"/\\|?*' else char
        for char in value
    )
    sanitized = sanitized.strip().rstrip(".")
    sanitized = " ".join(sanitized.split())
    return sanitized or "untitled"


@dataclass
class ExportedTreePage:
    page_id: str
    title: str
    output_file: str
    source_url: str | None
    parent_page_id: str | None


def export_page_tree(
    *,
    root_page: dict[str, Any],
    output_dir: Path,
    fetch_page: Callable[[str], dict[str, Any]],
    list_child_pages: Callable[[str], Iterable[dict[str, Any]]],
    base_url: str,
    mermaid_macro_name: str | None = None,
) -> list[ExportedTreePage]:
    exported: list[ExportedTreePage] = []

    def export_node(page: dict[str, Any], parent_dir: Path) -> None:
        title = page.get("title") or "Untitled"
        page_dir = parent_dir / sanitize_path_component(title)
        page_dir.mkdir(parents=True, exist_ok=True)

        page_id = str(page["id"])
        ancestors = page.get("ancestors") or []
        parent_page_id = ancestors[-1].get("id") if ancestors else None

        exporter = MarkdownExporter(
            base_url=base_url,
            page_id=page_id,
            mermaid_macro_name=mermaid_macro_name,
        )
        markdown = exporter.convert_page(
            {
                **page,
                "parent_page_id": parent_page_id,
            }
        )
        output_file = page_dir / "index.md"
        output_file.write_text(markdown, encoding="utf-8")

        exported.append(
            ExportedTreePage(
                page_id=page_id,
                title=title,
                output_file=str(output_file),
                source_url=page.get("webui_url"),
                parent_page_id=parent_page_id,
            )
        )

        for child in list_child_pages(page_id):
            child_page = fetch_page(str(child["id"]))
            export_node(child_page, page_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    export_node(root_page, output_dir)
    return exported
