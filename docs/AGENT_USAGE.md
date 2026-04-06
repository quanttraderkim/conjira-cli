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
- Obsidian work folders for final exported Markdown
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

Update an approved Confluence page:

```bash
./bin/conjira --env-file ./local/agent.env update-page --allow-write --page-id 100002 --append-html "<p>Updated by agent.</p>"
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

## Safety rules

- Do not pass PATs in chat unless explicitly requested for emergency debugging.
- Prefer `--env-file ./local/agent.env` over raw flags so Keychain names and allowlists stay consistent.
- This project does not implement delete commands.
- Write commands require `--allow-write`.
- If `CONFLUENCE_ALLOWED_*` or `JIRA_ALLOWED_*` values are set, treat them as hard safety boundaries rather than suggestions.

## Local setup

If `local/agent.env` is missing, create it from `local/agent.env.example`.

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
./bin/conjira --env-file ./local/agent.env auth-check
./bin/conjira --env-file ./local/agent.env jira-auth-check
```
