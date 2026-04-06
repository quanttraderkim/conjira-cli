from __future__ import annotations

import argparse
import json
import mimetypes
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


def _read_text_arg(raw_text: Optional[str], file_path: Optional[str]) -> str:
    if raw_text:
        return raw_text
    if file_path:
        return Path(file_path).read_text(encoding="utf-8")
    return ""


def _read_json_arg(raw_json: Optional[str], file_path: Optional[str]) -> Dict[str, Any]:
    if raw_json:
        return json.loads(raw_json)
    if file_path:
        return json.loads(Path(file_path).read_text(encoding="utf-8"))
    return {}


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
    create_page_body_group = create_page.add_mutually_exclusive_group(required=True)
    create_page_body_group.add_argument("--body-html")
    create_page_body_group.add_argument("--body-file")

    update_page = subparsers.add_parser("update-page", help="Update an existing Confluence page")
    update_page.add_argument("--page-id", required=True)
    update_page.add_argument("--allow-write", action="store_true")
    update_page.add_argument("--title")
    update_page.add_argument("--body-html")
    update_page.add_argument("--body-file")
    update_page.add_argument("--append-html")
    update_page.add_argument("--append-file")

    upload_attachment = subparsers.add_parser(
        "upload-attachment",
        help="Upload or update a Confluence attachment on a page",
    )
    upload_attachment.add_argument("--page-id", required=True)
    upload_attachment.add_argument("--file", required=True)
    upload_attachment.add_argument("--comment")
    upload_attachment.add_argument("--allow-write", action="store_true")
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
    jira_create_issue_description_group = jira_create_issue.add_mutually_exclusive_group()
    jira_create_issue_description_group.add_argument("--description")
    jira_create_issue_description_group.add_argument("--description-file")
    jira_create_issue_fields_group = jira_create_issue.add_mutually_exclusive_group()
    jira_create_issue_fields_group.add_argument("--fields-json")
    jira_create_issue_fields_group.add_argument("--fields-file")

    jira_add_comment = subparsers.add_parser("jira-add-comment", help="Add a Jira issue comment")
    jira_add_comment.add_argument("--issue-key", required=True)
    jira_add_comment.add_argument("--allow-write", action="store_true")
    jira_comment_group = jira_add_comment.add_mutually_exclusive_group(required=True)
    jira_comment_group.add_argument("--body")
    jira_comment_group.add_argument("--body-file")

    return parser


def _require_allow_write(allow_write: bool) -> None:
    if not allow_write:
        raise ConfigError("Write commands require --allow-write.")


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


def _render_text(payload: Dict[str, Any]) -> str:
    return "\n".join("{0}: {1}".format(key, value) for key, value in payload.items())


def _emit(payload: Dict[str, Any], output_mode: str) -> None:
    if output_mode == "text":
        print(_render_text(payload))
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _is_jira_command(command: str) -> bool:
    return command.startswith("jira-")


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
        payload = client.summarize_page(page)
        payload["body_html"] = (((page.get("body") or {}).get("storage") or {}).get("value")) or ""
        exporter = MarkdownExporter(base_url=settings.base_url, page_id=args.page_id)
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
        exporter = MarkdownExporter(base_url=settings.base_url, page_id=str(metadata["page_id"]))
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
        _require_allow_write(args.allow_write)
        _assert_confluence_create_allowed(
            space_key=args.space_key,
            parent_id=args.parent_id,
            allowed_space_keys=settings.allowed_space_keys,
            allowed_parent_ids=settings.allowed_parent_ids,
        )
        body_html = _read_text_arg(args.body_html, args.body_file)
        page = client.create_page(
            space_key=args.space_key,
            parent_id=args.parent_id,
            title=args.title,
            body_html=body_html,
        )
        return client.summarize_page(page)
    if args.command == "update-page":
        _require_allow_write(args.allow_write)
        _assert_confluence_update_allowed(
            page_id=args.page_id,
            allowed_page_ids=settings.allowed_page_ids,
        )
        new_body_html = (
            _read_text_arg(args.body_html, args.body_file)
            if (args.body_html or args.body_file)
            else None
        )
        append_html = (
            _read_text_arg(args.append_html, args.append_file)
            if (args.append_html or args.append_file)
            else None
        )
        if new_body_html is None and append_html is None and args.title is None:
            raise ConfigError(
                "update-page requires at least one of --title, --body-html/--body-file, or --append-html/--append-file."
            )
        page = client.update_page(
            page_id=args.page_id,
            new_title=args.title,
            new_body_html=new_body_html,
            append_html=append_html,
        )
        return client.summarize_page(page)
    if args.command == "upload-attachment":
        _require_allow_write(args.allow_write)
        _assert_confluence_update_allowed(
            page_id=args.page_id,
            allowed_page_ids=settings.allowed_page_ids,
        )
        file_path = Path(args.file)
        attachment = client.upload_attachment(
            page_id=args.page_id,
            file_name=file_path.name,
            content=file_path.read_bytes(),
            content_type=mimetypes.guess_type(file_path.name)[0] or "application/octet-stream",
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
        _require_allow_write(args.allow_write)
        _assert_jira_project_allowed(
            project_key=args.project_key,
            allowed_project_keys=settings.allowed_project_keys,
        )
        description = _read_text_arg(args.description, args.description_file)
        extra_fields = _read_json_arg(args.fields_json, args.fields_file)
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
        _require_allow_write(args.allow_write)
        _assert_jira_issue_allowed(
            issue_key=args.issue_key,
            allowed_issue_keys=settings.allowed_issue_keys,
        )
        comment = client.add_comment(
            issue_key=args.issue_key,
            body=_read_text_arg(args.body, args.body_file),
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
        error_payload: Dict[str, Any] = {"error": str(exc)}
        if isinstance(exc, (ConfluenceError, JiraError)):
            error_payload["status_code"] = exc.status_code
            if exc.payload is not None:
                error_payload["payload"] = exc.payload
        print(json.dumps(error_payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
