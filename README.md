# conjira-cli

Unofficial, agent-friendly CLI for self-hosted Confluence and Jira.

Korean version: [README.ko.md](README.ko.md)

`conjira-cli` is a small Python command-line tool for teams that run Confluence and Jira on their own infrastructure and want a practical local interface for scripts, coding agents, and Markdown workflows. It wraps standard Atlassian REST APIs behind a simple CLI, supports safer local credential handling, and adds guardrails for write operations.

This repository is intentionally sanitized for sharing. It does not include real company URLs, PATs, project keys, page IDs, issue keys, or exported workspace data.

You do not need to be a Python developer to get value from this repository. If you already use a local coding agent such as Codex, Claude Code, or another shell-capable agent, you can hand the repo to the agent, point it at your local `agent.env`, and ask for tasks like “export this Confluence page to Markdown”, “refresh this stale wiki note”, or “search Jira for issues created this week”. The agent can read this README, follow `docs/AGENT_USAGE.md`, and run the CLI for you.

## The problem this solves

If your team uses self-hosted Confluence and Jira, official cloud-native connectors are often not enough. You still have the REST APIs, but the missing piece is usually a reusable local tool that makes those APIs easy to use from a shell or from local coding agents.

`conjira-cli` is built for that gap. It helps when you want to read Confluence pages, export them to Markdown, refresh stale exports from the live wiki, summarize inline comment threads, search Jira with JQL, or create and update content without hardcoding PATs into source files or chat transcripts.

## What you can do with it

- read Confluence pages and search with CQL
- export Confluence pages to Markdown for note systems, docs folders, or knowledge bases
- create or update Confluence pages from either storage HTML or Markdown
- detect stale Markdown exports and refresh them from the live page
- fetch and export grouped Confluence inline comment threads
- upload attachments to Confluence pages
- read Jira issues, search with JQL, inspect create metadata, create issues, and add comments
- enforce write safety with `--allow-write` plus optional allowlists

## Who this is for

This tool is aimed at self-hosted Atlassian environments first, especially Server/Data Center style deployments. The current tested path uses Personal Access Tokens with Bearer auth against self-hosted base URLs, which matches the on-premise Atlassian pattern much better than Atlassian Cloud. Official references: [Atlassian Cloud basic auth](https://developer.atlassian.com/cloud/jira/service-desk/basic-auth-for-rest-apis/) and [Atlassian Personal Access Tokens](https://confluence.atlassian.com/enterprise/using-personal-access-tokens-1026032365.html).

## Demo

Validate both products:

```bash
./bin/conjira --env-file ./local/agent.env auth-check
./bin/conjira --env-file ./local/agent.env jira-auth-check
```

Export a Confluence page to Markdown:

```bash
./bin/conjira --env-file ./local/agent.env export-page-md --page-id 123456 --output-dir "/path/to/notes"
```

Create a Confluence page directly from Markdown:

```bash
./bin/conjira --env-file ./local/agent.env create-page --allow-write --space-key DOCS --parent-id 100001 --title "Markdown page" --body-markdown-file ./notes/demo.md
```

Check whether an exported file is stale and refresh it if the live page changed:

```bash
./bin/conjira --env-file ./local/agent.env check-page-md-freshness --file "/path/to/notes/page.md"
./bin/conjira --env-file ./local/agent.env refresh-page-md --file "/path/to/notes/page.md"
```

Summarize inline comment threads on a Confluence page:

```bash
./bin/conjira --env-file ./local/agent.env export-inline-comments-md --page-id 123456 --status open --output-dir "/path/to/notes"
```

Search Jira and fetch an issue:

```bash
./bin/conjira --env-file ./local/agent.env jira-search --jql 'project = DEMO ORDER BY created DESC' --limit 5
./bin/conjira --env-file ./local/agent.env jira-get-issue --issue-key DEMO-123
```

Short sample output blocks, using synthetic values:

```json
{
  "base_url": "https://confluence.example.com",
  "authenticated": true,
  "space_count_sample": 1,
  "first_space_key": "DOCS"
}
```

```json
{
  "page_id": "123456",
  "title": "Quarterly planning notes",
  "output_file": "/path/to/notes/Quarterly planning notes.md",
  "source_url": "https://confluence.example.com/pages/viewpage.action?pageId=123456",
  "used_staging_local": false
}
```

```json
{
  "key": "DEMO-123",
  "summary": "Roll out the new onboarding flow",
  "status": "In Progress",
  "issue_type": "Task",
  "assignee": "Alex Kim",
  "browse_url": "https://jira.example.com/browse/DEMO-123"
}
```

## Set up in about 5 minutes

```bash
git clone https://github.com/quanttraderkim/conjira-cli.git
cd conjira-cli
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -e .
```

If you do not want to install the package yet, the checked-in wrappers work directly:

```bash
./bin/conjira --help
./bin/conjira-cli --help
```

Create a local config file:

```bash
cp ./local/agent.env.example ./local/agent.env
```

## Credential handling

The recommended setup depends on your OS.

On macOS, the best local experience is to keep PATs in Keychain and store only non-secret machine settings in `local/agent.env`.

```dotenv
CONFLUENCE_BASE_URL=https://confluence.example.com
CONFLUENCE_PAT_KEYCHAIN_SERVICE=conjira-cli
CONFLUENCE_PAT_KEYCHAIN_ACCOUNT=confluence-prod
CONFLUENCE_EXPORT_DEFAULT_DIR=/path/to/notes/Confluence Inbox
CONFLUENCE_EXPORT_STAGING_DIR=/absolute/path/to/conjira-cli/local/exports

JIRA_BASE_URL=https://jira.example.com
JIRA_PAT_KEYCHAIN_SERVICE=conjira-cli
JIRA_PAT_KEYCHAIN_ACCOUNT=jira-prod
```

Store the Confluence PAT in Keychain:

```bash
read -s "PAT?Enter Confluence PAT: "; echo
security add-generic-password -U -s conjira-cli -a confluence-prod -w "$PAT"
unset PAT
```

Store the Jira PAT in Keychain:

```bash
read -s "PAT?Enter Jira PAT: "; echo
security add-generic-password -U -s conjira-cli -a jira-prod -w "$PAT"
unset PAT
```

On Linux or Windows, use environment variables or token files instead of Keychain. For example:

```dotenv
CONFLUENCE_BASE_URL=https://confluence.example.com
CONFLUENCE_PAT=your-confluence-pat
CONFLUENCE_EXPORT_DEFAULT_DIR=/path/to/notes

JIRA_BASE_URL=https://jira.example.com
JIRA_PAT=your-jira-pat
```

Or point the CLI at token files:

```dotenv
CONFLUENCE_BASE_URL=https://confluence.example.com
CONFLUENCE_PAT_FILE=/path/to/confluence.token

JIRA_BASE_URL=https://jira.example.com
JIRA_PAT_FILE=/path/to/jira.token
```

Then verify the connection:

```bash
./bin/conjira --env-file ./local/agent.env auth-check
./bin/conjira --env-file ./local/agent.env jira-auth-check
```

## Common commands

Read a Confluence page:

```bash
./bin/conjira --env-file ./local/agent.env get-page --page-id 123456 --expand body.storage,space,version
```

Export a Confluence page to Markdown:

```bash
./bin/conjira --env-file ./local/agent.env export-page-md --page-id 123456 --output-dir "/path/to/work-folder"
```

Export grouped inline comment threads:

```bash
./bin/conjira --env-file ./local/agent.env export-inline-comments-md --page-id 123456 --status open --output-dir "/path/to/work-folder"
```

Create or update a Confluence page:

```bash
./bin/conjira --env-file ./local/agent.env create-page --allow-write --space-key DOCS --parent-id 100001 --title "CLI test page" --body-html "<p>Hello from conjira</p>"
./bin/conjira --env-file ./local/agent.env update-page --allow-write --page-id 100002 --append-html "<p>Updated by conjira</p>"
```

Create or update a Confluence page from Markdown:

```bash
./bin/conjira --env-file ./local/agent.env create-page --allow-write --space-key DOCS --parent-id 100001 --title "Markdown page" --body-markdown "# Demo\n\n- Item A"
./bin/conjira --env-file ./local/agent.env update-page --allow-write --page-id 100002 --append-markdown-file ./notes/update.md
```

Search Jira and fetch an issue:

```bash
./bin/conjira --env-file ./local/agent.env jira-search --jql 'project = DEMO ORDER BY created DESC' --limit 5
./bin/conjira --env-file ./local/agent.env jira-get-issue --issue-key DEMO-123
```

Create a Jira issue or add a comment:

```bash
./bin/conjira --env-file ./local/agent.env jira-create-issue --allow-write --project-key DEMO --issue-type-name Task --summary "CLI issue test" --description "Created from conjira"
./bin/conjira --env-file ./local/agent.env jira-add-comment --allow-write --issue-key DEMO-123 --body "Comment from conjira"
```

## Configuration

The CLI resolves configuration in this order:

1. explicit CLI flags such as `--base-url` and `--token`
2. environment variables
3. values loaded from `--env-file`

Confluence settings:

- `CONFLUENCE_BASE_URL`
- `CONFLUENCE_PAT`
- `CONFLUENCE_PAT_FILE`
- `CONFLUENCE_PAT_KEYCHAIN_SERVICE`
- `CONFLUENCE_PAT_KEYCHAIN_ACCOUNT`
- `CONFLUENCE_TIMEOUT_SECONDS`
- `CONFLUENCE_ALLOWED_SPACE_KEYS`
- `CONFLUENCE_ALLOWED_PARENT_IDS`
- `CONFLUENCE_ALLOWED_PAGE_IDS`
- `CONFLUENCE_EXPORT_DEFAULT_DIR`
- `CONFLUENCE_EXPORT_STAGING_DIR`

Jira settings:

- `JIRA_BASE_URL`
- `JIRA_PAT`
- `JIRA_PAT_FILE`
- `JIRA_PAT_KEYCHAIN_SERVICE`
- `JIRA_PAT_KEYCHAIN_ACCOUNT`
- `JIRA_TIMEOUT_SECONDS`
- `JIRA_ALLOWED_PROJECT_KEYS`
- `JIRA_ALLOWED_ISSUE_KEYS`

## Safety model

This CLI intentionally does not implement delete commands for Confluence pages or Jira issues.

All write commands require `--allow-write`. That means a copied read command does not mutate Confluence or Jira unless the caller explicitly opts in.

For stronger guardrails, define write allowlists in `local/agent.env`. If `CONFLUENCE_ALLOWED_*` or `JIRA_ALLOWED_*` values are set, writes fail closed outside the approved spaces, parents, pages, projects, or issue keys even if the PAT itself has broader permissions.

## Export strategy

Use `local/` only for machine-local config, temporary files, and staging artifacts. Final Markdown exports should usually go into your real notes folder, docs workspace, or knowledge base, not into the CLI repository itself.

The recommended pattern is to set `CONFLUENCE_EXPORT_DEFAULT_DIR` to an inbox or work folder, keep `CONFLUENCE_EXPORT_STAGING_DIR` pointed at `local/exports`, use `--output-dir` when the final destination is already known, and use `--staging-local` only when you want a short-lived preview.

## Markdown import notes

Markdown upload is a best-effort conversion to Confluence storage HTML. It works well for common headings, paragraphs, lists, blockquotes, fenced code blocks, tables, links, images, and simple wiki-style links. It is not a perfect round-trip for complex Confluence macros, merged tables, or deeply nested layouts, so treat Markdown import as a practical authoring path rather than a lossless document converter.

Use `--body-file` and `--append-file` only for storage HTML files. If your source file is Markdown, use `--body-markdown-file` or `--append-markdown-file` so the CLI converts it before upload.

## Agent usage

If another local coding agent needs to use this project, point it to [docs/AGENT_USAGE.md](docs/AGENT_USAGE.md). That document is written for tools that can run shell commands on the same machine.

## License

This repository is released under the MIT License. See [LICENSE](LICENSE).
