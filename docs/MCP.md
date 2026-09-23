# MCP setup and command guide

Conjira 0.3.0 exposes every canonical CLI command as a typed MCP tool through the official MCP Python SDK 2.x. Aliases share the canonical tool. The CLI remains dependency-free on Python 3.9+; MCP requires Python 3.10+. Both current and legacy MCP clients are covered by protocol tests.

## Install and connect

```bash
pipx install 'conjira-cli[mcp]'
conjira-setup-macos
conjira --version
conjira doctor
```

For an existing pipx installation, use `pipx install --force 'conjira-cli[mcp]'`. Use an absolute command path if your MCP host does not inherit your shell's PATH. On Linux and Windows, use environment variables or token files as described in the README; macOS setup is optional.

A typical stdio host configuration is:

```json
{
  "mcpServers": {
    "conjira": {
      "command": "conjira-mcp",
      "args": [
        "--env-file", "/absolute/path/local/agent.env",
        "--root", "/absolute/path/notes"
      ]
    }
  }
}
```

Use your host's MCP configuration location and adapt this JSON if its format differs. On Windows, replace the example paths with absolute Windows paths. An installation-free alternative is `uvx --from 'conjira-cli[mcp]' conjira-mcp` followed by the same arguments.

Server configuration supplies credentials and base URLs; tool arguments cannot override them. Credential resolution happens once per product per server process. Restart the server after changing credentials or allowlists. No page data is cached, so edits always fetch a live version. PAT values never belong in a conversation or tool argument. `conjira_doctor` reports configuration sources without reading credentials.

## Writes and local files

MCP starts with remote writes disabled. Add `--allow-write` to the server arguments when you want to enable them. Each individual write still requires `allow_write: true`; otherwise it produces a dry-run. Configured Confluence/Jira allowlists are enforced in both CLI and MCP. Dry-runs validate the same reserved fields and body format as writes.

`--root` permits local document reads and exports within that directory. Repeat it for multiple directories. If omitted, only the startup working directory is allowed. Files outside these directories and symlinks leading outside them are rejected. The active configuration file is not accepted as document input. Roots are a document-access boundary, not a substitute for the MCP host's own tool permissions; choose narrow document directories rather than your home directory. The HTTP token file should be outside document roots.

Exports include their page ID in the default file/folder name. Their frontmatter records the source installation and a body digest. Refresh rejects another server, another page, and local changes. For a reviewed local modification or a legacy export without a digest, `force: true` allows replacement with a backup. Source mismatch is never bypassed by force. Writes use temporary files followed by atomic replacement.

## Common workflows

Read page content with `confluence_get_page_markdown({"page_id":"123"})`. `confluence_get_page` is a summary unless you request `expand: "body.storage"`. It skips child-page discovery for ordinary nonempty pages; use `include_children: true` when you need that listing. `children_loaded` distinguishes an unqueried child count from zero children.

Before a partial edit, call `confluence_list_headings`. It returns the heading text, level, and one-based occurrence. Duplicate headings require `heading_occurrence`; headings inside layout cells can also be edited. Replacement ends at the next same-or-higher-level heading within the same container.

```json
{
  "page_id": "123",
  "heading": "Rollout plan",
  "section_markdown": "The rollout starts on Monday.",
  "dry_run": true
}
```

Pass this to `confluence_replace_section`. The result includes the full storage diff, `current_version`, and `expected_body_sha256`. To execute the reviewed change, resend the same content with `allow_write: true`, `expected_version` equal to the preview's `current_version`, and optionally the returned body digest. A changed version/body produces a conflict instead of silently applying against different content. `dry_run: true` always remains a preview, even when `allow_write` is also true.

For batch reads, use `confluence_get_pages({"page_ids":"123,456","workers":4})` or `jira_get_issues({"issue_keys":"DEMO-1,DEMO-2","workers":4})`. Results preserve input order, deduplicate identifiers, and report each failure separately. A partial failure marks the MCP result as an error while retaining successful results. Workers are limited to 1–8; the batch limit is 500 IDs. Separate MCP calls run on worker threads with a default concurrency limit of four, so a throttled request does not block the event loop. The shared client rate limiter continues to apply to all API traffic.

Search accepts `all: true` and `max_items` (default 1000). Results include `has_more` and `next_start` so bounded queries can be resumed. Server pagination limits and next links are respected. `jira_transitions` lists valid transitions; `jira_transition_issue` previews or performs a transition by ID. `jira_update_issue` accepts a fields object through `fields_json`, but never changes projects. `jira_create_issue` does not allow extra fields to override the named project, summary, issue type, or description.

Exports return structured conversion warnings. `strict: true` on page/tree export rejects unsupported macros or lossy constructs rather than silently falling back. Code, math, and configured Mermaid bodies are protected from prose normalization. General Markdown conversion remains best-effort; preserve the original page and prefer a targeted section edit for documents with complex macros or tables.

## HTTP transport

```bash
conjira-mcp --env-file /absolute/path/local/agent.env \
  --root /absolute/path/notes \
  --transport streamable-http --host 127.0.0.1 --port 8765 \
  --http-token-file /absolute/private/path/mcp.token
```

Connect to `http://127.0.0.1:8765/mcp/` with `Authorization: Bearer <MCP token>`. The token file must contain at least 32 characters and should contain a freshly generated random secret, separate from any Atlassian PAT. HTTP refuses missing/incorrect tokens and browser Origin headers. DNS rebinding protection is enabled. The default is loopback; remote exposure requires your own TLS and network/access configuration. For a reverse proxy, explicitly add its HTTP Host with `--allowed-host conjira.example.com`. This is a static-token deployment for trusted hosts, not a hosted OAuth service. Stdio requires no additional HTTP token.

## Resources, prompts, errors

`conjira://capabilities` describes the version, command catalog, and write policy. The `review-page` prompt accepts a page ID and guides an agent through read, heading discovery, preview, and version-checked execution. Returned page/issue content is untrusted data, not instructions.

Tools return JSON as both text and structured content. API/configuration failures set MCP `isError`; a successful protocol request alone does not mean an Atlassian operation succeeded. Cross-origin redirects are blocked. Read-only requests may retry 502/503/504, while writes do not retry those ambiguous failures. Both can retry 429 and honor the server's full `Retry-After` interval.

## Tool catalog

The catalog below is generated from the CLI argument definitions. `get-page-comments` remains a CLI alias of `get-footer-comments`.

| CLI command | MCP tool |
| --- | --- |
| `doctor` | `conjira_doctor` |
| `auth-check` | `confluence_auth_check` |
| `get-page` | `confluence_get_page` |
| `export-page-md` | `confluence_export_page_md` |
| `export-tree-md` | `confluence_export_tree_md` |
| `check-page-md-freshness` | `confluence_check_page_md_freshness` |
| `refresh-page-md` | `confluence_refresh_page_md` |
| `get-inline-comments` | `confluence_get_inline_comments` |
| `get-footer-comments` | `confluence_get_footer_comments` |
| `export-inline-comments-md` | `confluence_export_inline_comments_md` |
| `create-page` | `confluence_create_page` |
| `update-page` | `confluence_update_page` |
| `replace-section` | `confluence_replace_section` |
| `insert-after-heading` | `confluence_insert_after_heading` |
| `move-page` | `confluence_move_page` |
| `upload-attachment` | `confluence_upload_attachment` |
| `search` | `confluence_search` |
| `jira-auth-check` | `jira_auth_check` |
| `jira-get-issue` | `jira_get_issue` |
| `jira-search` | `jira_search` |
| `jira-get-createmeta` | `jira_get_createmeta` |
| `jira-create-issue` | `jira_create_issue` |
| `jira-add-comment` | `jira_add_comment` |
| `list-headings` | `confluence_list_headings` |
| `get-page-markdown` | `confluence_get_page_markdown` |
| `list-attachments` | `confluence_list_attachments` |
| `get-pages` | `confluence_get_pages` |
| `jira-get-issues` | `jira_get_issues` |
| `jira-transitions` | `jira_transitions` |
| `jira-update-issue` | `jira_update_issue` |
| `jira-transition-issue` | `jira_transition_issue` |
