# Changelog

## 0.3.0

### MCP and workflows

Added `conjira-mcp` using the official MCP SDK 2.x, with 31 tools covering every canonical CLI command, structured results/errors, a capability resource, and a page-review prompt. Supports stdio and bearer-protected Streamable HTTP, with explicit write enablement, per-call write intent, document roots, and bounded concurrency. The CLI keeps its zero-runtime-dependency installation; MCP is an optional extra requiring Python 3.10+.

Added heading discovery and occurrence selection inside layout containers, exact storage diffs, expected-version/body checks, direct Markdown reads, bounded batch page/issue reads, complete attachment listing, paginated search with resume metadata, Jira field updates/status transitions, `--version`, and credential-free configuration diagnostics.

### Correctness and safety

Fixed all nine reproduced review cases: code export operator/entity corruption, CDATA mutation during Markdown import, Jira extra-field project allowlist bypass, cross-origin Authorization forwarding, export filename collisions, refresh across different source servers, premature pagination completion, false authentication success on login HTML, and shortened Retry-After intervals. Additional review fixes enforce space/project allowlists on existing-object writes and prevent identifier path injection. Authentication checks now verify the current user, not generic server/space availability.

Exports use source/page identity, local-edit digests, backups, and atomic file replacement. Conversion warnings and strict export make unsupported constructs visible. Read-only transient 5xx errors retry conservatively; writes do not blindly retry them.

### Performance and delivery

Ordinary page reads skip unnecessary child-page enumeration. Tree exports reuse expanded child-page bodies, avoiding a second content fetch for each supported child. MCP retains per-product settings/clients instead of repeatedly resolving Keychain credentials. Batch reads run with bounded concurrency under the shared API rate limiter. `scripts/benchmark_reads.py` measures a reproducible local mock workload; its results are not production latency guarantees.

CI covers Linux, macOS, and Windows, including a dependency-free Python 3.9 path and MCP protocol tests on supported Python versions. Publishing now waits for CI and validates a fresh installation of the built wheel before Trusted Publishing.

### Upgrade notes

Default export filenames/folders now include `--<page ID>`. Existing exports remain readable; refreshing a legacy file without a content digest requires `--force` and creates a backup. A refresh never overrides source/page mismatch. `auth-check` and `jira-auth-check` now return authenticated user information. `get-page` only discovers children when the page is empty or `--include-children` is requested; `children_loaded` indicates whether the child count is known. Arbitrary extra fields can no longer override explicit Jira create arguments. Restart long-running MCP servers after changing credentials or allowlists.
