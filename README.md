# conjira-cli

[![CI](https://github.com/quanttraderkim/conjira-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/quanttraderkim/conjira-cli/actions/workflows/ci.yml) [![PyPI version](https://img.shields.io/pypi/v/conjira-cli)](https://pypi.org/project/conjira-cli/) [![Python versions](https://img.shields.io/pypi/pyversions/conjira-cli)](https://pypi.org/project/conjira-cli/) [![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/quanttraderkim/conjira-cli/blob/main/LICENSE)

Unofficial, agent-friendly CLI for self-hosted Confluence and Jira.

Korean version: [README.ko.md](README.ko.md)

Release notes for maintainers: [docs/RELEASING.md](docs/RELEASING.md)

`conjira-cli` is a small Python command-line tool for teams that run Confluence and Jira on their own infrastructure and want a practical local interface for scripts, coding agents, and Markdown workflows. It wraps standard Atlassian REST APIs behind a simple CLI, supports safer local credential handling, and adds guardrails for write operations.

You do not need to be a Python developer to get value from this repository. If you already use a local coding agent or another shell-capable AI tool, you can hand the repo to the agent, point it at your local `agent.env`, and ask for tasks like “export this Confluence page to Markdown”, “refresh this stale wiki note”, or “search Jira for issues created this week”. The agent can read this README, follow `docs/AGENT_USAGE.md`, and run the CLI for you.

## The problem this solves

If your team uses self-hosted Confluence and Jira, official cloud-native connectors are often not enough. You still have the REST APIs, but the missing piece is usually a reusable local tool that makes those APIs easy to use from a shell or from local coding agents.

`conjira-cli` is built for that gap. It helps when you want to read Confluence pages, export them to Markdown, refresh stale exports from the live wiki, summarize inline comment threads, search Jira with JQL, or create and update content without hardcoding PATs into source files or chat transcripts.

For report-style pages, it can also preserve a small set of Confluence-native presentation macros while still keeping Markdown as the source of truth. The current bridge covers Mermaid, Markdown callouts such as `> [!INFO]`, `> [!NOTE]`, `> [!TIP]`, and `> [!WARNING]`, expandable blocks with `> [!EXPAND]`, and inline status badges with `:status[In Progress]{color=yellow}`.

## What you can do with it

- read Confluence pages and search with CQL
- export Confluence pages to Markdown for note systems, docs folders, or knowledge bases
- create or update Confluence pages from either storage HTML or Markdown
- detect stale Markdown exports and refresh them from the live page
- fetch and export grouped Confluence inline comment threads
- upload attachments to Confluence pages
- read Jira issues, search with JQL, inspect create metadata, create issues, and add comments
- preview writes with `--dry-run`, then enforce them with `--allow-write` plus optional allowlists

## Who this is for

This tool is aimed at self-hosted Atlassian environments first, especially Server/Data Center style deployments. The current tested path uses Personal Access Tokens with Bearer auth against self-hosted base URLs, which matches the on-premise Atlassian pattern much better than Atlassian Cloud. Official references: [Atlassian Cloud basic auth](https://developer.atlassian.com/cloud/jira/service-desk/basic-auth-for-rest-apis/) and [Atlassian Personal Access Tokens](https://confluence.atlassian.com/enterprise/using-personal-access-tokens-1026032365.html).

## Set up in about 5 minutes

If you already use `pipx`, the shortest install path is:

```bash
pipx install conjira-cli
conjira-setup-macos
```

If you do not use `pipx`, a simple fallback is:

```bash
python3 -m pip install --user conjira-cli
conjira-setup-macos
```

Or install from a local checkout:

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

On macOS, you can do the first-time Keychain-based setup with one script instead of editing `local/agent.env` by hand:

```bash
conjira-setup-macos
```

The script stores PATs in macOS Keychain, writes only non-secret settings to `local/agent.env`, and can run `auth-check` for you at the end.
It uses the default Keychain target names automatically, so most users only need to enter the base URL and PAT.
PAT prompts are hidden on screen by design. Paste the token and press Enter even if nothing appears while typing.
It does not write PAT values to `~/.zshrc` or other shell profile files.
If you keep working in the same folder, `conjira` will auto-load `./local/agent.env` so you do not need to pass `--env-file` each time.
If you are running directly from a source checkout before installing entrypoints, you can still use:

```bash
bash scripts/setup-conjira-macos.sh
```

## Ask an agent

If you are using Codex, Claude Code, or another shell-capable local coding agent, you can usually ask in plain language instead of writing the command yourself. For example:

- "Use conjira to export Confluence page `123456` to Markdown and save it into my notes folder."
- "Check whether this exported Confluence note is stale, refresh it from the live wiki, and summarize what changed."
- "Search Jira for issues created this week in project `DEMO` and give me a short summary."
- "Replace the `Rollout plan` section on page `123456`, show me a dry-run preview, and only write if the preview looks correct."

If you want to run the CLI directly, start with these short commands:

```bash
conjira auth-check
conjira jira-auth-check
conjira export-page-md --page-id 123456 --output-dir "/path/to/notes"
```

If you run the CLI from a different folder, pass the config file explicitly with `--env-file /path/to/local/agent.env`.

## Prompt templates by document type

When you ask an agent to upload or update a document, results are better if you tell it what kind of document it is, whether Markdown should remain the source of truth, and whether the Confluence page should stay plain or become more presentation-friendly.

For skill specs or evaluation docs, a good request is:

```text
Use conjira to upload this Markdown file as a Confluence page. Treat it as a skill spec, keep the Markdown structure as the source of truth, preserve headings and tables, and only use Confluence-native rendering where it helps readability without changing the document's meaning.
```

For service planning docs or PRDs, a good request is:

```text
Use conjira to turn this Markdown file into a Confluence PRD. Keep the content faithful to the source, but make it easier to read in Confluence. Add status, callouts, and expand blocks where they improve readability, and organize the page around summary, background, problem, scope, flow, risks, and open questions.
```

For strategy reports or review decks, a good request is:

```text
Use conjira to publish this Markdown file as a report-style Confluence page. Keep the source content intact, but optimize the page for presentation. Put the executive summary first, surface key decisions and risks early, and use status, info blocks, expand sections, and Mermaid where appropriate.
```

If you want to stay closer to raw Markdown, say `keep this Markdown-first and avoid extra presentation macros`. If you want a more polished Confluence page, say `optimize this for Confluence readability while keeping the source content intact`.

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

## Credential handling

The recommended setup depends on your OS.

On macOS, the best local experience is to keep PATs in Keychain and store only non-secret machine settings in `local/agent.env`.

If you want the easiest path on macOS, run:

```bash
conjira-setup-macos
```

If you prefer to set everything manually, use the Keychain flow below.

```dotenv
CONFLUENCE_BASE_URL=https://confluence.example.com
CONFLUENCE_PAT_KEYCHAIN_SERVICE=conjira-cli
CONFLUENCE_PAT_KEYCHAIN_ACCOUNT=confluence-prod
CONFLUENCE_EXPORT_DEFAULT_DIR=/path/to/notes/wiki-exports
CONFLUENCE_EXPORT_STAGING_DIR=/absolute/path/to/conjira-cli/local/exports
# Optional: convert ```mermaid fences to a Confluence Mermaid macro
# CONFLUENCE_MERMAID_MACRO_NAME=mermaid-macro

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
# Optional: convert ```mermaid fences to a Confluence Mermaid macro
# CONFLUENCE_MERMAID_MACRO_NAME=mermaid-macro

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
conjira auth-check
conjira jira-auth-check
```

If you run the CLI outside the configured folder, use `--env-file /path/to/local/agent.env` explicitly.

## Common commands

Read a Confluence page:

```bash
conjira --env-file ./local/agent.env get-page --page-id 123456 --expand body.storage,space,version
```

Export a Confluence page to Markdown:

```bash
conjira --env-file ./local/agent.env export-page-md --page-id 123456 --output-dir "/path/to/work-folder"
```

Export a Confluence page tree to nested Markdown folders:

```bash
conjira --env-file ./local/agent.env export-tree-md --page-id 123456 --output-dir "/path/to/work-folder"
```

Export grouped inline comment threads:

```bash
conjira --env-file ./local/agent.env export-inline-comments-md --page-id 123456 --status open --output-dir "/path/to/work-folder"
```

Create or update a Confluence page:

```bash
conjira --env-file ./local/agent.env create-page --allow-write --space-key DOCS --parent-id 100001 --title "CLI test page" --body-html "<p>Hello from conjira</p>"
conjira --env-file ./local/agent.env update-page --allow-write --page-id 100002 --append-html "<p>Updated by conjira</p>"
```

Create or update a Confluence page from Markdown:

```bash
conjira --env-file ./local/agent.env create-page --allow-write --space-key DOCS --parent-id 100001 --title "Markdown page" --body-markdown "# Demo\n\n- Item A"
conjira --env-file ./local/agent.env update-page --allow-write --page-id 100002 --append-markdown-file ./notes/update.md
```

Replace one named section on an existing Confluence page:

```bash
conjira --env-file ./local/agent.env replace-section --allow-write --page-id 100002 --heading "Rollout plan" --section-markdown-file ./notes/rollout.md
```

Move an existing Confluence page under a different parent page:

```bash
conjira --env-file ./local/agent.env move-page --dry-run --page-id 100002 --new-parent-id 100001
conjira --env-file ./local/agent.env move-page --allow-write --page-id 100002 --new-parent-id 100001
```

Preview a Confluence or Jira write first:

```bash
conjira --env-file ./local/agent.env update-page --dry-run --page-id 100002 --append-markdown-file ./notes/update.md
conjira --env-file ./local/agent.env jira-create-issue --dry-run --project-key DEMO --issue-type-name Task --summary "Preview issue" --description "No write yet"
```

Search Jira and fetch an issue:

```bash
conjira --env-file ./local/agent.env jira-search --jql 'project = DEMO ORDER BY created DESC' --limit 5
conjira --env-file ./local/agent.env jira-get-issue --issue-key DEMO-123
```

Inspect updated timestamps or recent comments when needed:

```bash
conjira jira-get-issue --issue-key DEMO-123 --include-comments --comments-limit 2
conjira jira-get-issue --issue-key DEMO-123 --raw --fields summary,updated,comment
conjira jira-search --jql 'project = DEMO ORDER BY updated DESC' --raw --fields summary,updated
```

Create a Jira issue or add a comment:

```bash
conjira --env-file ./local/agent.env jira-create-issue --allow-write --project-key DEMO --issue-type-name Task --summary "CLI issue test" --description "Created from conjira"
conjira --env-file ./local/agent.env jira-add-comment --allow-write --issue-key DEMO-123 --body "Comment from conjira"
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

Write commands either require `--allow-write`, or `--dry-run` when you only want a preview. That means a copied read command does not mutate Confluence or Jira unless the caller explicitly opts in.

For stronger guardrails, define write allowlists in `local/agent.env`. If `CONFLUENCE_ALLOWED_*` or `JIRA_ALLOWED_*` values are set, writes fail closed outside the approved spaces, parents, pages, projects, or issue keys even if the PAT itself has broader permissions.

## Common failure hints

When the CLI hits a common API failure, it now returns a `guidance` field alongside the raw error. The most common cases are:

- `401`: check the PAT, the credential source being used, and whether the base URL points at the right product host
- `403`: check product permissions and any configured allowlists
- `404`: check the page ID, issue key, or target path and confirm the PAT owner can see it in the web UI
- `409`: refresh live content and retry, especially for Confluence updates after concurrent edits
- `429` and `5xx`: retry after a short delay and reduce request volume if you are looping

## Export strategy

Use `local/` only for machine-local config, temporary files, and staging artifacts. Final Markdown exports should usually go into your real notes folder, docs workspace, or knowledge base, not into the CLI repository itself.

The recommended pattern is to set `CONFLUENCE_EXPORT_DEFAULT_DIR` to an inbox or work folder, keep `CONFLUENCE_EXPORT_STAGING_DIR` pointed at `local/exports`, use `--output-dir` when the final destination is already known, and use `--staging-local` only when you want a short-lived preview.

## Markdown import notes

Markdown upload is a best-effort conversion to Confluence storage HTML. It works well for common headings, paragraphs, lists, blockquotes, fenced code blocks, tables, links, images, simple wiki-style links, and the currently supported report macros (`mermaid`, callouts, `expand`, and `:status[Title]{color=blue}`). It is not a perfect round-trip for complex Confluence macros, merged tables, or deeply nested layouts, so treat Markdown import as a practical authoring path rather than a lossless document converter.

Use `--body-file` and `--append-file` only for storage HTML files. If your source file is Markdown, use `--body-markdown-file` or `--append-markdown-file` so the CLI converts it before upload.

## Agent usage

If another local coding agent needs to use this project, point it to [docs/AGENT_USAGE.md](docs/AGENT_USAGE.md). That document is written for tools that can run shell commands on the same machine.

## License

This repository is released under the MIT License. See [LICENSE](LICENSE).
