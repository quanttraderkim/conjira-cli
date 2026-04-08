from __future__ import annotations

import argparse
import html
import json
import mimetypes
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from conjira_cli.client import (
    ConfluenceClient,
    ConfluenceError,
    JiraClient,
    JiraError,
)
from conjira_cli.config import (
    ConfigError,
    build_confluence_settings,
    build_jira_settings,
)
from conjira_cli.inline_comments import render_inline_comment_summary_markdown
from conjira_cli.markdown_export import MarkdownExporter
from conjira_cli.markdown_import import markdown_to_storage_html
from conjira_cli.section_edit import SectionEditError, replace_section_html
from conjira_cli.tree_export import export_page_tree, sanitize_path_component


def _read_text_arg(raw_text: Optional[str], file_path: Optional[str]) -> str:
    if raw_text is not None:
        return raw_text
    if file_path:
        return Path(file_path).read_text(encoding="utf-8")
    return ""


def _read_json_arg(raw_json: Optional[str], file_path: Optional[str]) -> Dict[str, Any]:
    if raw_json is not None:
        return json.loads(raw_json)
    if file_path:
        return json.loads(Path(file_path).read_text(encoding="utf-8"))
    return {}


def _read_confluence_body_arg(
    raw_html: Optional[str],
    html_file: Optional[str],
    raw_markdown: Optional[str],
    markdown_file: Optional[str],
    mermaid_macro_name: Optional[str] = None,
) -> str:
    if raw_html is not None or html_file is not None:
        return _read_text_arg(raw_html, html_file)
    return markdown_to_storage_html(
        _read_text_arg(raw_markdown, markdown_file),
        mermaid_macro_name=mermaid_macro_name,
    )


def _read_optional_confluence_body_arg(
    raw_html: Optional[str],
    html_file: Optional[str],
    raw_markdown: Optional[str],
    markdown_file: Optional[str],
    mermaid_macro_name: Optional[str] = None,
) -> Optional[str]:
    if all(value is None for value in [raw_html, html_file, raw_markdown, markdown_file]):
        return None
    return _read_confluence_body_arg(
        raw_html,
        html_file,
        raw_markdown,
        markdown_file,
        mermaid_macro_name=mermaid_macro_name,
    )


def _truncate_preview(value: str, limit: int = 240) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _preview_text(value: Optional[str], limit: int = 240) -> Optional[str]:
    if value is None:
        return None
    collapsed = re.sub(r"\s+", " ", value).strip()
    if not collapsed:
        return None
    return _truncate_preview(collapsed, limit=limit)


def _preview_html(value: Optional[str], limit: int = 240) -> Optional[str]:
    if value is None:
        return None
    preview = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    preview = re.sub(r"</p\s*>", "\n\n", preview, flags=re.IGNORECASE)
    preview = re.sub(r"<li[^>]*>", "- ", preview, flags=re.IGNORECASE)
    preview = re.sub(r"</li\s*>", "\n", preview, flags=re.IGNORECASE)
    preview = re.sub(r"<[^>]+>", " ", preview)
    preview = html.unescape(preview).replace("\xa0", " ")
    return _preview_text(preview, limit=limit)


def _sanitize_markdown_filename(title: str) -> str:
    sanitized = "".join(
        "_" if char in '<>:"/\\|?*' else char
        for char in title
    )
    sanitized = sanitized.strip().rstrip(".")
    sanitized = " ".join(sanitized.split())
    return (sanitized or "untitled") + ".md"


def _strip_frontmatter_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _read_markdown_frontmatter(path: Path) -> Dict[str, str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ConfigError("Markdown frontmatter not found in: {0}".format(path))

    frontmatter: Dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return frontmatter
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = _strip_frontmatter_value(value)

    raise ConfigError("Markdown frontmatter is not closed in: {0}".format(path))


def _read_export_metadata(path: Path) -> Dict[str, Any]:
    frontmatter = _read_markdown_frontmatter(path)
    page_id = frontmatter.get("confluence_page_id")
    if not page_id:
        raise ConfigError("confluence_page_id is missing in Markdown frontmatter: {0}".format(path))

    local_version = frontmatter.get("confluence_version")
    return {
        "page_id": page_id,
        "local_version": int(local_version) if local_version else None,
        "source_url": frontmatter.get("source_url"),
        "title": frontmatter.get("title"),
    }


def _page_export_payload(page: Dict[str, Any]) -> Dict[str, Any]:
    payload = ConfluenceClient.summarize_page(page)
    payload["body_html"] = (((page.get("body") or {}).get("storage") or {}).get("value")) or ""
    payload["ancestors"] = page.get("ancestors") or []
    return payload


def _default_export_staging_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "local" / "exports"


def _resolve_export_output_path(
    *,
    title: str,
    output_file: Optional[str],
    output_dir: Optional[str],
    filename: Optional[str],
    staging_local: bool,
    default_dir: Optional[str],
    staging_dir: Optional[str],
) -> Path:
    if output_file and (output_dir or filename or staging_local):
        raise ConfigError(
            "Markdown export does not allow combining --output-file with --output-dir, --filename, or --staging-local."
        )

    if output_file:
        return Path(output_file)

    target_dir: Optional[Path] = None
    if output_dir:
        target_dir = Path(output_dir)
    elif staging_local:
        target_dir = Path(staging_dir) if staging_dir else _default_export_staging_dir()
    elif default_dir:
        target_dir = Path(default_dir)

    if target_dir is None:
        raise ConfigError(
            "Markdown export requires --output-file or --output-dir, or CONFLUENCE_EXPORT_DEFAULT_DIR, or --staging-local."
        )

    resolved_filename = filename or _sanitize_markdown_filename(title)
    if not resolved_filename.endswith(".md"):
        resolved_filename += ".md"
    return target_dir / resolved_filename


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="conjira")
    parser.add_argument("--base-url")
    parser.add_argument("--token")
    parser.add_argument("--token-file")
    parser.add_argument("--token-keychain-service")
    parser.add_argument("--token-keychain-account")
    parser.add_argument("--env-file")
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--output", choices=["json", "text"], default="json")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("auth-check", help="Validate Confluence base URL and PAT")

    get_page = subparsers.add_parser("get-page", help="Fetch a Confluence page by ID")
    get_page.add_argument("--page-id", required=True)
    get_page.add_argument("--expand")

    export_page_md = subparsers.add_parser(
        "export-page-md",
        help="Export a Confluence page to a Markdown file",
    )
    export_page_md.add_argument("--page-id", required=True)
    export_page_md.add_argument("--output-file")
    export_page_md.add_argument("--output-dir")
    export_page_md.add_argument("--filename")
    export_page_md.add_argument("--staging-local", action="store_true")

    export_tree_md = subparsers.add_parser(
        "export-tree-md",
        help="Export a Confluence page tree to nested Markdown folders",
    )
    export_tree_md.add_argument("--page-id", required=True)
    export_tree_md.add_argument("--output-dir")
    export_tree_md.add_argument("--staging-local", action="store_true")

    check_page_md_freshness = subparsers.add_parser(
        "check-page-md-freshness",
        help="Check whether an exported Markdown file is stale against Confluence",
    )
    check_page_md_freshness.add_argument("--file", required=True)

    refresh_page_md = subparsers.add_parser(
        "refresh-page-md",
        help="Refresh an exported Markdown file from the current Confluence page",
    )
    refresh_page_md.add_argument("--file", required=True)

    get_inline_comments = subparsers.add_parser(
        "get-inline-comments",
        help="Fetch Confluence inline comments and group them into threads",
    )
    get_inline_comments.add_argument("--page-id", required=True)
    get_inline_comments.add_argument("--limit", type=int, default=200)
    get_inline_comments.add_argument(
        "--status",
        choices=["all", "open", "resolved", "dangling"],
        default="all",
    )

    export_inline_comments_md = subparsers.add_parser(
        "export-inline-comments-md",
        help="Export grouped Confluence inline comments to a Markdown file",
    )
    export_inline_comments_md.add_argument("--page-id", required=True)
    export_inline_comments_md.add_argument("--limit", type=int, default=200)
    export_inline_comments_md.add_argument(
        "--status",
        choices=["all", "open", "resolved", "dangling"],
        default="open",
    )
    export_inline_comments_md.add_argument("--output-file")
    export_inline_comments_md.add_argument("--output-dir")
    export_inline_comments_md.add_argument("--filename")
    export_inline_comments_md.add_argument("--staging-local", action="store_true")

    create_page = subparsers.add_parser("create-page", help="Create a new Confluence page")
    create_page.add_argument("--space-key", required=True)
    create_page.add_argument("--parent-id")
    create_page.add_argument("--title", required=True)
    create_page.add_argument("--allow-write", action="store_true")
    create_page.add_argument("--dry-run", action="store_true")
    create_page_body_group = create_page.add_mutually_exclusive_group(required=True)
    create_page_body_group.add_argument("--body-html")
    create_page_body_group.add_argument("--body-file")
    create_page_body_group.add_argument("--body-markdown")
    create_page_body_group.add_argument("--body-markdown-file")

    update_page = subparsers.add_parser("update-page", help="Update an existing Confluence page")
    update_page.add_argument("--page-id", required=True)
    update_page.add_argument("--allow-write", action="store_true")
    update_page.add_argument("--dry-run", action="store_true")
    update_page.add_argument("--title")
    update_page_body_group = update_page.add_mutually_exclusive_group()
    update_page_body_group.add_argument("--body-html")
    update_page_body_group.add_argument("--body-file")
    update_page_body_group.add_argument("--body-markdown")
    update_page_body_group.add_argument("--body-markdown-file")
    update_page_append_group = update_page.add_mutually_exclusive_group()
    update_page_append_group.add_argument("--append-html")
    update_page_append_group.add_argument("--append-file")
    update_page_append_group.add_argument("--append-markdown")
    update_page_append_group.add_argument("--append-markdown-file")

    replace_section = subparsers.add_parser(
        "replace-section",
        help="Replace the content under a specific Confluence heading",
    )
    replace_section.add_argument("--page-id", required=True)
    replace_section.add_argument("--heading", required=True)
    replace_section.add_argument("--allow-write", action="store_true")
    replace_section.add_argument("--dry-run", action="store_true")
    replace_section_body_group = replace_section.add_mutually_exclusive_group(required=True)
    replace_section_body_group.add_argument("--section-html")
    replace_section_body_group.add_argument("--section-file")
    replace_section_body_group.add_argument("--section-markdown")
    replace_section_body_group.add_argument("--section-markdown-file")

    move_page = subparsers.add_parser(
        "move-page",
        help="Move an existing Confluence page under a different parent page",
    )
    move_page.add_argument("--page-id", required=True)
    move_page.add_argument("--new-parent-id", required=True)
    move_page.add_argument("--allow-write", action="store_true")
    move_page.add_argument("--dry-run", action="store_true")

    upload_attachment = subparsers.add_parser(
        "upload-attachment",
        help="Upload or update a Confluence attachment on a page",
    )
    upload_attachment.add_argument("--page-id", required=True)
    upload_attachment.add_argument("--file", required=True)
    upload_attachment.add_argument("--comment")
    upload_attachment.add_argument("--allow-write", action="store_true")
    upload_attachment.add_argument("--dry-run", action="store_true")
    upload_attachment.add_argument("--major-edit", action="store_true")

    confluence_search = subparsers.add_parser("search", help="Search Confluence with CQL")
    confluence_search.add_argument("--cql", required=True)
    confluence_search.add_argument("--limit", type=int, default=10)
    confluence_search.add_argument("--start", type=int, default=0)
    confluence_search.add_argument("--expand")

    subparsers.add_parser("jira-auth-check", help="Validate Jira base URL and PAT")

    jira_get_issue = subparsers.add_parser("jira-get-issue", help="Fetch a Jira issue by key")
    jira_get_issue.add_argument("--issue-key", required=True)
    jira_get_issue.add_argument("--fields")
    jira_get_issue.add_argument("--expand")

    jira_search = subparsers.add_parser("jira-search", help="Search Jira with JQL")
    jira_search.add_argument("--jql", required=True)
    jira_search.add_argument("--limit", type=int, default=10)
    jira_search.add_argument("--start", type=int, default=0)
    jira_search.add_argument("--fields")
    jira_search.add_argument("--expand")

    jira_get_createmeta = subparsers.add_parser(
        "jira-get-createmeta",
        help="Fetch Jira create metadata for a project",
    )
    jira_get_createmeta.add_argument("--project-key", required=True)
    jira_get_createmeta.add_argument("--issue-type-name")
    jira_get_createmeta.add_argument("--expand", default="projects.issuetypes.fields")

    jira_create_issue = subparsers.add_parser("jira-create-issue", help="Create a Jira issue")
    jira_create_issue.add_argument("--project-key", required=True)
    jira_create_issue.add_argument("--summary", required=True)
    jira_create_issue.add_argument("--issue-type-name", required=True)
    jira_create_issue.add_argument("--allow-write", action="store_true")
    jira_create_issue.add_argument("--dry-run", action="store_true")
    jira_create_issue_description_group = jira_create_issue.add_mutually_exclusive_group()
    jira_create_issue_description_group.add_argument("--description")
    jira_create_issue_description_group.add_argument("--description-file")
    jira_create_issue_fields_group = jira_create_issue.add_mutually_exclusive_group()
    jira_create_issue_fields_group.add_argument("--fields-json")
    jira_create_issue_fields_group.add_argument("--fields-file")

    jira_add_comment = subparsers.add_parser("jira-add-comment", help="Add a Jira issue comment")
    jira_add_comment.add_argument("--issue-key", required=True)
    jira_add_comment.add_argument("--allow-write", action="store_true")
    jira_add_comment.add_argument("--dry-run", action="store_true")
    jira_comment_group = jira_add_comment.add_mutually_exclusive_group(required=True)
    jira_comment_group.add_argument("--body")
    jira_comment_group.add_argument("--body-file")

    return parser


def _require_write_intent(allow_write: bool, dry_run: bool) -> None:
    if not allow_write and not dry_run:
        raise ConfigError("Write commands require --allow-write or --dry-run.")


def _assert_confluence_create_allowed(
    *,
    space_key: str,
    parent_id: Optional[str],
    allowed_space_keys: Optional[set[str]],
    allowed_parent_ids: Optional[set[str]],
) -> None:
    if allowed_space_keys is not None and space_key not in allowed_space_keys:
        raise ConfigError(
            "Write blocked: space key {0} is not in CONFLUENCE_ALLOWED_SPACE_KEYS.".format(space_key)
        )
    if allowed_parent_ids is not None:
        if not parent_id:
            raise ConfigError("Write blocked: parent ID is required by CONFLUENCE_ALLOWED_PARENT_IDS.")
        if parent_id not in allowed_parent_ids:
            raise ConfigError(
                "Write blocked: parent ID {0} is not in CONFLUENCE_ALLOWED_PARENT_IDS.".format(parent_id)
            )


def _assert_confluence_update_allowed(
    *,
    page_id: str,
    allowed_page_ids: Optional[set[str]],
) -> None:
    if allowed_page_ids is not None and page_id not in allowed_page_ids:
        raise ConfigError(
            "Write blocked: page ID {0} is not in CONFLUENCE_ALLOWED_PAGE_IDS.".format(page_id)
        )


def _assert_jira_project_allowed(
    *,
    project_key: str,
    allowed_project_keys: Optional[set[str]],
) -> None:
    if allowed_project_keys is not None and project_key not in allowed_project_keys:
        raise ConfigError(
            "Write blocked: project key {0} is not in JIRA_ALLOWED_PROJECT_KEYS.".format(project_key)
        )


def _assert_jira_issue_allowed(
    *,
    issue_key: str,
    allowed_issue_keys: Optional[set[str]],
) -> None:
    if allowed_issue_keys is not None and issue_key not in allowed_issue_keys:
        raise ConfigError(
            "Write blocked: issue key {0} is not in JIRA_ALLOWED_ISSUE_KEYS.".format(issue_key)
        )


def _confluence_create_preview(
    *,
    space_key: str,
    parent_id: Optional[str],
    title: str,
    body_html: str,
    body_source: str,
) -> Dict[str, Any]:
    return {
        "dry_run": True,
        "product": "confluence",
        "action": "create-page",
        "space_key": space_key,
        "parent_id": parent_id,
        "title": title,
        "body_source": body_source,
        "body_length": len(body_html),
        "body_preview": _preview_html(body_html),
    }


def _confluence_body_source(
    *,
    raw_html: Optional[str],
    html_file: Optional[str],
    raw_markdown: Optional[str],
    markdown_file: Optional[str],
) -> Optional[str]:
    if raw_html is not None or html_file is not None:
        return "storage_html"
    if raw_markdown is not None or markdown_file is not None:
        return "markdown"
    return None


def _confluence_update_preview(
    *,
    page: Dict[str, Any],
    new_title: Optional[str],
    new_body_html: Optional[str],
    append_html: Optional[str],
    body_source: Optional[str],
    append_source: Optional[str],
) -> Dict[str, Any]:
    current_summary = ConfluenceClient.summarize_page(page)
    current_body = (((page.get("body") or {}).get("storage") or {}).get("value")) or ""
    resulting_body = new_body_html if new_body_html is not None else current_body
    if append_html:
        resulting_body += append_html

    next_title = new_title or current_summary.get("title")
    return {
        "dry_run": True,
        "product": "confluence",
        "action": "update-page",
        "page_id": current_summary.get("id"),
        "space_key": current_summary.get("space_key"),
        "source_url": current_summary.get("webui_url"),
        "current_version": current_summary.get("version"),
        "current_title": current_summary.get("title"),
        "next_title": next_title,
        "title_changed": next_title != current_summary.get("title"),
        "body_replaced": new_body_html is not None,
        "body_appended": append_html is not None,
        "body_source": body_source,
        "append_source": append_source,
        "current_body_length": len(current_body),
        "next_body_length": len(resulting_body),
        "body_preview": _preview_html(resulting_body),
    }


def _confluence_replace_section_preview(
    *,
    page: Dict[str, Any],
    heading: str,
    result: Any,
    body_source: str,
) -> Dict[str, Any]:
    current_summary = ConfluenceClient.summarize_page(page)
    return {
        "dry_run": True,
        "product": "confluence",
        "action": "replace-section",
        "page_id": current_summary.get("id"),
        "space_key": current_summary.get("space_key"),
        "source_url": current_summary.get("webui_url"),
        "heading": heading,
        "matched_heading": result.matched_heading,
        "heading_level": result.heading_level,
        "body_source": body_source,
        "replaced_section": True,
        "old_section_preview": _preview_html(result.old_section_html),
        "new_section_preview": _preview_html(result.new_section_html),
        "resulting_body_preview": _preview_html(result.updated_body_html),
    }


def _confluence_move_page_preview(
    *,
    page: Dict[str, Any],
    new_parent_id: str,
) -> Dict[str, Any]:
    current_summary = ConfluenceClient.summarize_page(page)
    ancestors = page.get("ancestors") or []
    current_parent = ancestors[-1].get("id") if ancestors else None
    return {
        "dry_run": True,
        "product": "confluence",
        "action": "move-page",
        "page_id": current_summary.get("id"),
        "space_key": current_summary.get("space_key"),
        "source_url": current_summary.get("webui_url"),
        "title": current_summary.get("title"),
        "current_version": current_summary.get("version"),
        "current_parent_id": current_parent,
        "new_parent_id": new_parent_id,
        "parent_changed": current_parent != new_parent_id,
    }


def _confluence_attachment_preview(
    *,
    page_id: str,
    file_path: Path,
    content_type: str,
    comment: Optional[str],
    minor_edit: bool,
    existing_attachment: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    summary = (
        ConfluenceClient.summarize_attachment(existing_attachment)
        if existing_attachment is not None
        else None
    )
    return {
        "dry_run": True,
        "product": "confluence",
        "action": "upload-attachment",
        "page_id": page_id,
        "file_name": file_path.name,
        "file_size": file_path.stat().st_size,
        "content_type": content_type,
        "comment": comment,
        "minor_edit": minor_edit,
        "mode": "replace" if existing_attachment is not None else "create",
        "existing_attachment": summary,
    }


def _jira_create_issue_preview(
    *,
    client: JiraClient,
    project_key: str,
    summary: str,
    issue_type_name: str,
    description: Optional[str],
    extra_fields: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "dry_run": True,
        "product": "jira",
        "action": "jira-create-issue",
        "project_key": project_key,
        "summary": summary,
        "issue_type_name": issue_type_name,
        "description_preview": _preview_text(description),
        "description_length": len(description) if description is not None else 0,
        "extra_field_keys": sorted(extra_fields.keys()),
        "project_browse_url": "{0}/projects/{1}".format(client.base_url.rstrip("/"), project_key),
    }


def _jira_comment_preview(
    *,
    issue: Dict[str, Any],
    comment_body: str,
    client: JiraClient,
) -> Dict[str, Any]:
    summary = client.summarize_issue(issue)
    return {
        "dry_run": True,
        "product": "jira",
        "action": "jira-add-comment",
        "issue_key": summary.get("key"),
        "issue_summary": summary.get("summary"),
        "issue_status": summary.get("status"),
        "browse_url": summary.get("browse_url"),
        "comment_length": len(comment_body),
        "comment_preview": _preview_text(comment_body),
    }


def _render_text(payload: Dict[str, Any]) -> str:
    return "\n".join("{0}: {1}".format(key, value) for key, value in payload.items())


def _emit(payload: Dict[str, Any], output_mode: str) -> None:
    if output_mode == "text":
        print(_render_text(payload))
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _is_jira_command(command: str) -> bool:
    return command.startswith("jira-")


def _guidance_for_status(exc: Exception) -> list[str]:
    if not isinstance(exc, (ConfluenceError, JiraError)):
        return []

    status_code = exc.status_code
    product = "Confluence" if isinstance(exc, ConfluenceError) else "Jira"
    if status_code == 401:
        return [
            "Confirm the PAT is valid, active, and issued for {0}.".format(product),
            "Check that --base-url or {0}_BASE_URL points to the correct {1} host.".format(
                product.upper(),
                product,
            ),
            "If you use Keychain, env vars, or token files, confirm the CLI is reading the intended credential source.",
        ]
    if status_code == 403:
        return [
            "Check whether the PAT owner can access or edit the target object in the {0} web UI.".format(product),
            "If write allowlists are configured, verify the target is included in the approved spaces, pages, projects, or issue keys.",
            "If this is a write command, confirm the PAT owner has edit permission for the target content.",
        ]
    if status_code == 404:
        return [
            "Verify the base URL and identifier are correct, such as page ID, issue key, or attachment target page.",
            "Confirm the PAT owner can see the target object in the {0} web UI.".format(product),
            "If you exported content earlier, refresh from the live source before retrying.",
        ]
    if status_code == 409:
        return [
            "Refresh the live object and retry, because another edit may have changed the current version.",
            "For Confluence page updates, fetch the latest page before applying another write.",
        ]
    if status_code == 429:
        return [
            "The server asked you to slow down. Retry after a short delay.",
            "Reduce batch size, polling frequency, or repeated write attempts if you are automating a loop.",
        ]
    if status_code is not None and 500 <= status_code <= 599:
        return [
            "The Atlassian server returned a transient failure. Retry after a short delay.",
            "If the error persists, check whether the {0} instance is degraded or unavailable.".format(product),
        ]
    return []


def _guidance_for_config_error(message: str) -> list[str]:
    lowered = message.lower()
    if "missing confluence token" in lowered or "missing jira token" in lowered:
        return [
            "Provide a PAT with --token, a token file, or env or Keychain settings for the target product.",
            "If you expected Keychain lookup to work, verify the configured service and account names exist on this machine.",
        ]
    if "missing confluence base url" in lowered or "missing jira base url" in lowered:
        return [
            "Set the base URL with --base-url, an env var, or local agent.env before retrying.",
            "Make sure the URL points at the product root, not a specific page or issue path.",
        ]
    if "write blocked" in lowered:
        return [
            "The CLI safety allowlist rejected this target before any API write happened.",
            "Check CONFLUENCE_ALLOWED_* or JIRA_ALLOWED_* values in your local config and expand them only if this target is intentionally approved.",
        ]
    if "--allow-write or --dry-run" in lowered:
        return [
            "Use --dry-run to preview the change first, or add --allow-write to execute it intentionally.",
        ]
    if "update-page requires at least one" in lowered:
        return [
            "Provide a title change, a replacement body, or appended content before retrying update-page.",
        ]
    if "replace-section target heading" in lowered:
        return [
            "Check that the heading text exists exactly once on the live Confluence page before retrying replace-section.",
            "For the first iteration, replace-section is safest on text-first pages with clear heading structure.",
        ]
    if "move-page requires different" in lowered:
        return [
            "Choose a different parent page before retrying move-page.",
        ]
    if "failed to parse confluence storage html fragment" in lowered:
        return [
            "Check that the replacement input converts into valid Confluence storage HTML.",
            "If the source is Markdown, retry with simpler text-first content before using macro-heavy input.",
        ]
    return []


def _build_error_payload(exc: Exception) -> Dict[str, Any]:
    error_payload: Dict[str, Any] = {
        "error": str(exc),
        "error_type": type(exc).__name__,
    }

    guidance: list[str] = []
    if isinstance(exc, (ConfluenceError, JiraError)):
        error_payload["status_code"] = exc.status_code
        if exc.payload is not None:
            error_payload["payload"] = exc.payload
        guidance = _guidance_for_status(exc)
    elif isinstance(exc, ConfigError):
        guidance = _guidance_for_config_error(str(exc))
    elif isinstance(exc, FileNotFoundError):
        guidance = [
            "Check that the referenced local file exists and that the path is correct on this machine.",
        ]
    elif isinstance(exc, json.JSONDecodeError):
        guidance = [
            "Check that the JSON input is valid, especially fields files and inline JSON arguments.",
        ]

    if guidance:
        error_payload["guidance"] = guidance
    return error_payload


def _handle_confluence(args: argparse.Namespace) -> Dict[str, Any]:
    settings = build_confluence_settings(
        base_url=args.base_url,
        token=args.token,
        token_file=args.token_file,
        token_keychain_service=args.token_keychain_service,
        token_keychain_account=args.token_keychain_account,
        timeout_seconds=args.timeout,
        env_file=args.env_file,
    )
    client = ConfluenceClient(
        base_url=settings.base_url,
        token=settings.token,
        timeout_seconds=settings.timeout_seconds,
    )

    if args.command == "auth-check":
        return client.auth_check()
    if args.command == "get-page":
        page = client.get_page(args.page_id, expand=args.expand)
        payload = client.summarize_page(page)
        if args.expand and "body.storage" in args.expand:
            payload["body_html"] = (((page.get("body") or {}).get("storage") or {}).get("value"))
        return payload
    if args.command == "export-page-md":
        page = client.get_page(args.page_id, expand="body.storage,version,space")
        payload = _page_export_payload(page)
        exporter = MarkdownExporter(
            base_url=settings.base_url,
            page_id=args.page_id,
            mermaid_macro_name=settings.mermaid_macro_name,
        )
        markdown = exporter.convert_page(payload)
        output_path = _resolve_export_output_path(
            title=payload["title"] or "Untitled",
            output_file=args.output_file,
            output_dir=args.output_dir,
            filename=args.filename,
            staging_local=args.staging_local,
            default_dir=settings.export_default_dir,
            staging_dir=settings.export_staging_dir,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
        return {
            "page_id": args.page_id,
            "title": payload["title"],
            "output_file": str(output_path),
            "source_url": payload["webui_url"],
            "used_staging_local": str(output_path).startswith(
                str((Path(settings.export_staging_dir) if settings.export_staging_dir else _default_export_staging_dir()))
            ),
        }
    if args.command == "export-tree-md":
        root_page = client.get_page(args.page_id, expand="body.storage,version,space,ancestors")
        root_payload = _page_export_payload(root_page)
        output_base = (
            Path(args.output_dir)
            if args.output_dir
            else (
                Path(settings.export_staging_dir)
                if args.staging_local and settings.export_staging_dir
                else (
                    _default_export_staging_dir()
                    if args.staging_local
                    else (
                        Path(settings.export_default_dir)
                        if settings.export_default_dir
                        else None
                    )
                )
            )
        )
        if output_base is None:
            raise ConfigError(
                "Tree export requires --output-dir, or CONFLUENCE_EXPORT_DEFAULT_DIR, or --staging-local."
            )
        exported = export_page_tree(
            root_page=root_payload,
            output_dir=output_base,
            fetch_page=lambda page_id: _page_export_payload(
                client.get_page(page_id, expand="body.storage,version,space,ancestors")
            ),
            list_child_pages=client.list_child_pages,
            base_url=settings.base_url,
            mermaid_macro_name=settings.mermaid_macro_name,
        )
        root_dir = str(output_base / sanitize_path_component(root_payload["title"] or "Untitled"))
        return {
            "page_id": args.page_id,
            "title": root_payload["title"],
            "root_output_dir": root_dir,
            "exported_count": len(exported),
            "exported_pages": [
                {
                    "page_id": item.page_id,
                    "title": item.title,
                    "output_file": item.output_file,
                    "source_url": item.source_url,
                    "parent_page_id": item.parent_page_id,
                }
                for item in exported
            ],
            "used_staging_local": str(output_base).startswith(
                str((Path(settings.export_staging_dir) if settings.export_staging_dir else _default_export_staging_dir()))
            ),
        }
    if args.command == "check-page-md-freshness":
        file_path = Path(args.file)
        metadata = _read_export_metadata(file_path)
        page = client.get_page(str(metadata["page_id"]), expand="version,space")
        remote_summary = client.summarize_page(page)
        remote_version = remote_summary.get("version")
        local_version = metadata["local_version"]
        return {
            "file": str(file_path),
            "page_id": str(metadata["page_id"]),
            "title": remote_summary.get("title") or metadata.get("title"),
            "local_version": local_version,
            "remote_version": remote_version,
            "is_stale": (
                False if local_version is None or remote_version is None else local_version < remote_version
            ),
            "source_url": remote_summary.get("webui_url") or metadata.get("source_url"),
        }
    if args.command == "refresh-page-md":
        file_path = Path(args.file)
        metadata = _read_export_metadata(file_path)
        page = client.get_page(str(metadata["page_id"]), expand="body.storage,version,space")
        payload = client.summarize_page(page)
        payload["body_html"] = (((page.get("body") or {}).get("storage") or {}).get("value")) or ""
        exporter = MarkdownExporter(
            base_url=settings.base_url,
            page_id=str(metadata["page_id"]),
            mermaid_macro_name=settings.mermaid_macro_name,
        )
        markdown = exporter.convert_page(payload)
        file_path.write_text(markdown, encoding="utf-8")
        return {
            "file": str(file_path),
            "page_id": str(metadata["page_id"]),
            "title": payload["title"],
            "version": payload["version"],
            "source_url": payload["webui_url"],
            "refreshed": True,
        }
    if args.command == "get-inline-comments":
        page = client.get_page(args.page_id, expand="version,space")
        comments = client.list_inline_comments(
            args.page_id,
            limit=args.limit,
        )
        return client.summarize_inline_comments(
            page=page,
            comments=comments,
            status_filter=args.status,
        )
    if args.command == "export-inline-comments-md":
        page = client.get_page(args.page_id, expand="version,space")
        comments = client.list_inline_comments(
            args.page_id,
            limit=args.limit,
        )
        summary = client.summarize_inline_comments(
            page=page,
            comments=comments,
            status_filter=args.status,
        )
        markdown = render_inline_comment_summary_markdown(summary)
        output_path = _resolve_export_output_path(
            title="{0} - Inline Comment Summary".format(summary["page_title"] or "Untitled"),
            output_file=args.output_file,
            output_dir=args.output_dir,
            filename=args.filename,
            staging_local=args.staging_local,
            default_dir=settings.export_default_dir,
            staging_dir=settings.export_staging_dir,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
        return {
            "page_id": args.page_id,
            "title": summary["page_title"],
            "output_file": str(output_path),
            "source_url": summary["page_url"],
            "thread_count": summary["thread_count"],
            "open_thread_count": summary["open_thread_count"],
            "used_staging_local": str(output_path).startswith(
                str((Path(settings.export_staging_dir) if settings.export_staging_dir else _default_export_staging_dir()))
            ),
        }
    if args.command == "create-page":
        _require_write_intent(args.allow_write, args.dry_run)
        _assert_confluence_create_allowed(
            space_key=args.space_key,
            parent_id=args.parent_id,
            allowed_space_keys=settings.allowed_space_keys,
            allowed_parent_ids=settings.allowed_parent_ids,
        )
        body_html = _read_confluence_body_arg(
            args.body_html,
            args.body_file,
            args.body_markdown,
            args.body_markdown_file,
            mermaid_macro_name=settings.mermaid_macro_name,
        )
        body_source = _confluence_body_source(
            raw_html=args.body_html,
            html_file=args.body_file,
            raw_markdown=args.body_markdown,
            markdown_file=args.body_markdown_file,
        )
        if args.dry_run:
            return _confluence_create_preview(
                space_key=args.space_key,
                parent_id=args.parent_id,
                title=args.title,
                body_html=body_html,
                body_source=body_source or "unknown",
            )
        page = client.create_page(
            space_key=args.space_key,
            parent_id=args.parent_id,
            title=args.title,
            body_html=body_html,
        )
        return client.summarize_page(page)
    if args.command == "update-page":
        _require_write_intent(args.allow_write, args.dry_run)
        _assert_confluence_update_allowed(
            page_id=args.page_id,
            allowed_page_ids=settings.allowed_page_ids,
        )
        new_body_html = _read_optional_confluence_body_arg(
            args.body_html,
            args.body_file,
            args.body_markdown,
            args.body_markdown_file,
            mermaid_macro_name=settings.mermaid_macro_name,
        )
        append_html = _read_optional_confluence_body_arg(
            args.append_html,
            args.append_file,
            args.append_markdown,
            args.append_markdown_file,
            mermaid_macro_name=settings.mermaid_macro_name,
        )
        if new_body_html is None and append_html is None and args.title is None:
            raise ConfigError(
                "update-page requires at least one of --title, --body-html/--body-file, --body-markdown/--body-markdown-file, --append-html/--append-file, or --append-markdown/--append-markdown-file."
            )
        if args.dry_run:
            page = client.get_page(args.page_id, expand="body.storage,version,space")
            return _confluence_update_preview(
                page=page,
                new_title=args.title,
                new_body_html=new_body_html,
                append_html=append_html,
                body_source=_confluence_body_source(
                    raw_html=args.body_html,
                    html_file=args.body_file,
                    raw_markdown=args.body_markdown,
                    markdown_file=args.body_markdown_file,
                ),
                append_source=_confluence_body_source(
                    raw_html=args.append_html,
                    html_file=args.append_file,
                    raw_markdown=args.append_markdown,
                    markdown_file=args.append_markdown_file,
                ),
            )
        page = client.update_page(
            page_id=args.page_id,
            new_title=args.title,
            new_body_html=new_body_html,
            append_html=append_html,
        )
        return client.summarize_page(page)
    if args.command == "replace-section":
        _require_write_intent(args.allow_write, args.dry_run)
        _assert_confluence_update_allowed(
            page_id=args.page_id,
            allowed_page_ids=settings.allowed_page_ids,
        )
        replacement_html = _read_confluence_body_arg(
            args.section_html,
            args.section_file,
            args.section_markdown,
            args.section_markdown_file,
            mermaid_macro_name=settings.mermaid_macro_name,
        )
        page = client.get_page(args.page_id, expand="body.storage,version,space")
        current_body = (((page.get("body") or {}).get("storage") or {}).get("value")) or ""
        try:
            replacement = replace_section_html(
                current_body,
                heading=args.heading,
                replacement_html=replacement_html,
            )
        except SectionEditError as exc:
            raise ConfigError(str(exc)) from exc
        body_source = _confluence_body_source(
            raw_html=args.section_html,
            html_file=args.section_file,
            raw_markdown=args.section_markdown,
            markdown_file=args.section_markdown_file,
        )
        if args.dry_run:
            return _confluence_replace_section_preview(
                page=page,
                heading=args.heading,
                result=replacement,
                body_source=body_source or "unknown",
            )
        updated = client.update_page_from_snapshot(
            page,
            new_body_html=replacement.updated_body_html,
        )
        payload = client.summarize_page(updated)
        payload["action"] = "replace-section"
        payload["heading"] = args.heading
        payload["matched_heading"] = replacement.matched_heading
        return payload
    if args.command == "move-page":
        _require_write_intent(args.allow_write, args.dry_run)
        _assert_confluence_update_allowed(
            page_id=args.page_id,
            allowed_page_ids=settings.allowed_page_ids,
        )
        if settings.allowed_parent_ids is not None and args.new_parent_id not in settings.allowed_parent_ids:
            raise ConfigError(
                "Write blocked: parent ID {0} is not in CONFLUENCE_ALLOWED_PARENT_IDS.".format(
                    args.new_parent_id
                )
            )
        page = client.get_page(args.page_id, expand="body.storage,version,space,ancestors")
        ancestors = page.get("ancestors") or []
        current_parent = ancestors[-1].get("id") if ancestors else None
        if current_parent == args.new_parent_id:
            raise ConfigError("move-page requires different current and new parent IDs.")
        if args.dry_run:
            return _confluence_move_page_preview(
                page=page,
                new_parent_id=args.new_parent_id,
            )
        updated = client.update_page_from_snapshot(
            page,
            new_parent_id=args.new_parent_id,
        )
        payload = client.summarize_page(updated)
        payload["action"] = "move-page"
        payload["previous_parent_id"] = current_parent
        payload["new_parent_id"] = args.new_parent_id
        return payload
    if args.command == "upload-attachment":
        _require_write_intent(args.allow_write, args.dry_run)
        _assert_confluence_update_allowed(
            page_id=args.page_id,
            allowed_page_ids=settings.allowed_page_ids,
        )
        file_path = Path(args.file)
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        if args.dry_run:
            attachments = client.get_attachments(args.page_id)
            existing_attachment = None
            for item in attachments.get("results", []):
                if item.get("title") == file_path.name:
                    existing_attachment = item
                    break
            return _confluence_attachment_preview(
                page_id=args.page_id,
                file_path=file_path,
                content_type=content_type,
                comment=args.comment,
                minor_edit=not args.major_edit,
                existing_attachment=existing_attachment,
            )
        attachment = client.upload_attachment(
            page_id=args.page_id,
            file_name=file_path.name,
            content=file_path.read_bytes(),
            content_type=content_type,
            comment=args.comment,
            minor_edit=not args.major_edit,
        )
        results = attachment.get("results", []) if isinstance(attachment, dict) else []
        if results:
            return client.summarize_attachment(results[0])
        return {"status": "uploaded", "title": file_path.name}
    if args.command == "search":
        result = client.search(
            cql=args.cql,
            limit=args.limit,
            start=args.start,
            expand=args.expand,
        )
        return client.summarize_search_results(result.get("results", []))
    raise ConfigError("Unknown Confluence command: {0}".format(args.command))


def _handle_jira(args: argparse.Namespace) -> Dict[str, Any]:
    settings = build_jira_settings(
        base_url=args.base_url,
        token=args.token,
        token_file=args.token_file,
        token_keychain_service=args.token_keychain_service,
        token_keychain_account=args.token_keychain_account,
        timeout_seconds=args.timeout,
        env_file=args.env_file,
    )
    client = JiraClient(
        base_url=settings.base_url,
        token=settings.token,
        timeout_seconds=settings.timeout_seconds,
    )

    if args.command == "jira-auth-check":
        return client.auth_check()
    if args.command == "jira-get-issue":
        issue = client.get_issue(args.issue_key, fields=args.fields, expand=args.expand)
        return client.summarize_issue(issue)
    if args.command == "jira-search":
        result = client.search(
            jql=args.jql,
            limit=args.limit,
            start=args.start,
            fields=args.fields,
            expand=args.expand,
        )
        return client.summarize_search_results(result.get("issues", []))
    if args.command == "jira-get-createmeta":
        result = client.get_createmeta(
            project_key=args.project_key,
            issue_type_name=args.issue_type_name,
            expand=args.expand,
        )
        return client.summarize_createmeta(result)
    if args.command == "jira-create-issue":
        _require_write_intent(args.allow_write, args.dry_run)
        _assert_jira_project_allowed(
            project_key=args.project_key,
            allowed_project_keys=settings.allowed_project_keys,
        )
        description = _read_text_arg(args.description, args.description_file)
        extra_fields = _read_json_arg(args.fields_json, args.fields_file)
        if args.dry_run:
            return _jira_create_issue_preview(
                client=client,
                project_key=args.project_key,
                summary=args.summary,
                issue_type_name=args.issue_type_name,
                description=description if description else None,
                extra_fields=extra_fields,
            )
        issue = client.create_issue(
            project_key=args.project_key,
            summary=args.summary,
            issue_type_name=args.issue_type_name,
            description=description if description else None,
            extra_fields=extra_fields or None,
        )
        issue_key = issue.get("key")
        return {
            "id": issue.get("id"),
            "key": issue_key,
            "browse_url": client.browse_url(client.base_url, issue_key),
        }
    if args.command == "jira-add-comment":
        _require_write_intent(args.allow_write, args.dry_run)
        _assert_jira_issue_allowed(
            issue_key=args.issue_key,
            allowed_issue_keys=settings.allowed_issue_keys,
        )
        comment_body = _read_text_arg(args.body, args.body_file)
        if args.dry_run:
            issue = client.get_issue(args.issue_key)
            return _jira_comment_preview(
                issue=issue,
                comment_body=comment_body,
                client=client,
            )
        comment = client.add_comment(
            issue_key=args.issue_key,
            body=comment_body,
        )
        return {
            "id": comment.get("id"),
            "issue_key": args.issue_key,
            "browse_url": client.browse_url(client.base_url, args.issue_key),
        }
    raise ConfigError("Unknown Jira command: {0}".format(args.command))


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        payload = _handle_jira(args) if _is_jira_command(args.command) else _handle_confluence(args)
        _emit(payload, args.output)
        return 0
    except (ConfigError, ConfluenceError, JiraError, FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        error_payload = _build_error_payload(exc)
        print(json.dumps(error_payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
