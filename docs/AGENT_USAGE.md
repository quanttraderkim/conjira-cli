# AGENT_USAGE

This document is for local coding agents that can run shell commands on the same machine as the project.

## Project root

```bash
cd "/path/to/conjira-cli"
```

## Recommended entrypoint

Use the checked-in wrapper:

```bash
./bin/conjira --env-file ./local/agent.env auth-check
```

The `local/agent.env` file is intentionally gitignored. It stores machine-specific, non-secret configuration such as:

- Base URL
- optional credential source settings such as Keychain service/account names or token file paths
- optional Confluence and Jira write allowlists

The actual PAT should stay in a local secret store when possible, not in chat, not in source code, and not in tracked `.env` files.

On macOS, Keychain is the recommended local path. On Linux or Windows, prefer environment variables or token files.

The preferred storage policy is:

- `local/` for config, temporary files, and staging only
- your real notes folder, docs workspace, or knowledge base for final exported Markdown
- `CONFLUENCE_EXPORT_DEFAULT_DIR` as the default final destination
- `CONFLUENCE_EXPORT_STAGING_DIR` or `--staging-local` only for previews or short-lived working copies

## Typical commands

Confluence auth check:

```bash
./bin/conjira --env-file ./local/agent.env auth-check
```

Read a Confluence page:

```bash
./bin/conjira --env-file ./local/agent.env get-page --page-id 123456 --expand body.storage,space,version
```

Export a Confluence page to Markdown:

```bash
./bin/conjira --env-file ./local/agent.env export-page-md --page-id 123456 --output-file "/path/to/page.md"
```

Export to a known work folder:

```bash
./bin/conjira --env-file ./local/agent.env export-page-md --page-id 123456 --output-dir "/path/to/work-folder"
```

Export a Confluence page tree to nested work folders:

```bash
./bin/conjira --env-file ./local/agent.env export-tree-md --page-id 123456 --output-dir "/path/to/work-folder"
```

Export to staging under `local/exports`:

```bash
./bin/conjira --env-file ./local/agent.env export-page-md --page-id 123456 --staging-local
```

Before using an exported Markdown file as current context, check whether it is stale:

```bash
./bin/conjira --env-file ./local/agent.env check-page-md-freshness --file "/path/to/page.md"
```

If it is stale, refresh the same file in place:

```bash
./bin/conjira --env-file ./local/agent.env refresh-page-md --file "/path/to/page.md"
```

Read grouped inline comments on a Confluence page:

```bash
./bin/conjira --env-file ./local/agent.env get-inline-comments --page-id 123456 --status all
```

Export inline comment threads to Markdown:

```bash
./bin/conjira --env-file ./local/agent.env export-inline-comments-md --page-id 123456 --status open --output-dir "/path/to/work-folder"
```

Create a Confluence page under the approved parent:

```bash
./bin/conjira --env-file ./local/agent.env create-page --allow-write --space-key DOCS --parent-id 100001 --title "Agent Test" --body-html "<p>Created by agent.</p>"
```

Preview the same write without changing anything:

```bash
./bin/conjira --env-file ./local/agent.env create-page --dry-run --space-key DOCS --parent-id 100001 --title "Agent Test" --body-markdown "# Preview"
```

Create a Confluence page from Markdown:

```bash
./bin/conjira --env-file ./local/agent.env create-page --allow-write --space-key DOCS --parent-id 100001 --title "Markdown page" --body-markdown-file "/path/to/page.md"
```

Replace a named section under an existing Confluence heading:

```bash
./bin/conjira --env-file ./local/agent.env replace-section --allow-write --page-id 100002 --heading "Rollout plan" --section-markdown-file "/path/to/rollout.md"
```

Preview the same section replacement before writing:

```bash
./bin/conjira --env-file ./local/agent.env replace-section --dry-run --page-id 100002 --heading "Rollout plan" --section-markdown-file "/path/to/rollout.md"
```

Move an existing Confluence page to a new parent:

```bash
./bin/conjira --env-file ./local/agent.env move-page --dry-run --page-id 100002 --new-parent-id 100001
./bin/conjira --env-file ./local/agent.env move-page --allow-write --page-id 100002 --new-parent-id 100001
```

Update an approved Confluence page:

```bash
./bin/conjira --env-file ./local/agent.env update-page --allow-write --page-id 100002 --append-html "<p>Updated by agent.</p>"
```

Update an approved Confluence page from Markdown:

```bash
./bin/conjira --env-file ./local/agent.env update-page --allow-write --page-id 100002 --append-markdown-file "/path/to/update.md"
```

Upload or refresh a Confluence attachment:

```bash
./bin/conjira --env-file ./local/agent.env upload-attachment --allow-write --page-id 100002 --file ./local/chart.png --comment "Refresh chart"
```

Jira auth check:

```bash
./bin/conjira --env-file ./local/agent.env jira-auth-check
```

Read a Jira issue:

```bash
./bin/conjira --env-file ./local/agent.env jira-get-issue --issue-key DEMO-123
```

Search Jira with JQL:

```bash
./bin/conjira --env-file ./local/agent.env jira-search --jql 'project = DEMO ORDER BY created DESC' --limit 5
```

Create a Jira issue:

```bash
./bin/conjira --env-file ./local/agent.env jira-create-issue --allow-write --project-key DEMO --issue-type-name Task --summary "Agent-created issue" --description "Created by agent."
```

Add a Jira comment:

```bash
./bin/conjira --env-file ./local/agent.env jira-add-comment --allow-write --issue-key DEMO-123 --body "Comment from agent."
```

Preview a Jira write before using `--allow-write`:

```bash
./bin/conjira --env-file ./local/agent.env jira-add-comment --dry-run --issue-key DEMO-123 --body "Preview only"
```

## Safety rules

- Do not pass PATs in chat unless explicitly requested for emergency debugging.
- Prefer `--env-file ./local/agent.env` over raw flags so Keychain names and allowlists stay consistent.
- This project does not implement delete commands.
- Write commands require `--allow-write`, or `--dry-run` when you only want a preview.
- If `CONFLUENCE_ALLOWED_*` or `JIRA_ALLOWED_*` values are set, treat them as hard safety boundaries rather than suggestions.
- Markdown upload is a best-effort conversion to Confluence storage HTML. Prefer it for common text-first pages, not for macro-heavy round-trips.
- `--body-file` and `--append-file` are for storage HTML files. Use `--body-markdown-file` or `--append-markdown-file` for Markdown inputs.
- `replace-section` currently works best on text-first pages with clear heading structure. It intentionally fails when the target heading is missing or ambiguous.

## Local setup

If `local/agent.env` is missing, either create it from `local/agent.env.example` or, on macOS, run:

```bash
conjira-setup-macos
```

For most users, `conjira-setup-macos` only needs the product base URL and PAT. The default Keychain service/account names are filled in automatically. PAT prompts are hidden on screen, so paste the token and press Enter even if the input looks blank.
If the agent runs `conjira` from the same workspace folder, `./local/agent.env` will be loaded automatically. If it runs from somewhere else, pass `--env-file /path/to/local/agent.env` explicitly.

On macOS, store the Confluence PAT like this:

```bash
read -s "PAT?Enter Confluence PAT: "; echo
security add-generic-password -U -s conjira-cli -a confluence-prod -w "$PAT"
unset PAT
```

Store the Jira PAT like this:

```bash
read -s "PAT?Enter Jira PAT: "; echo
security add-generic-password -U -s conjira-cli -a jira-prod -w "$PAT"
unset PAT
```

If Keychain is not available, store PATs in env vars or token files instead:

```dotenv
CONFLUENCE_BASE_URL=https://confluence.example.com
CONFLUENCE_PAT=your-confluence-pat
JIRA_BASE_URL=https://jira.example.com
JIRA_PAT=your-jira-pat
```

Then verify:

```bash
./bin/conjira auth-check
./bin/conjira jira-auth-check
```
