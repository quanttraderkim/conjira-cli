"""Small shared operations used by CLI and MCP."""

from __future__ import annotations

import difflib
import hashlib
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from conjira_cli.client import ConfluenceError
from conjira_cli.config import ConfigError
from conjira_cli.section_edit import list_headings
from conjira_cli.client import url_origin


def snapshot_guard(page: dict[str, Any], args: Any) -> None:
    expected = getattr(args, "expected_version", None)
    actual = (page.get("version") or {}).get("number")
    if expected is not None and expected != actual:
        raise ConfluenceError(
            "Page changed since preview; fetch a fresh preview before writing.",
            status_code=409,
        )
    expected_body = getattr(args, "expected_body_sha256", None)
    body = (((page.get("body") or {}).get("storage") or {}).get("value")) or ""
    if expected_body and expected_body != hashlib.sha256(body.encode()).hexdigest():
        raise ConfluenceError("Page body changed since preview.", status_code=409)


def change_details(page: dict[str, Any], new_body: str) -> dict[str, Any]:
    old = (((page.get("body") or {}).get("storage") or {}).get("value")) or ""
    # Preserve complete diff; consumers may deliberately truncate its display.
    return {
        "current_version": (page.get("version") or {}).get("number"),
        "expected_body_sha256": hashlib.sha256(old.encode()).hexdigest(),
        "next_body_sha256": hashlib.sha256(new_body.encode()).hexdigest(),
        "diff": "".join(
            difflib.unified_diff(
                old.splitlines(True),
                new_body.splitlines(True),
                fromfile="current.storage.html",
                tofile="proposed.storage.html",
            )
        ),
        "changed": old != new_body,
    }


def batch_read(ids: str, fetch: Callable[[str], Any], workers: int) -> dict[str, Any]:
    keys = list(dict.fromkeys(key.strip() for key in ids.split(",") if key.strip()))
    if not keys or len(keys) > 500:
        raise ConfigError(
            "Batch requires between 1 and 500 comma-separated identifiers."
        )
    if not 1 <= workers <= 8:
        raise ConfigError("workers must be between 1 and 8")

    def one(key):
        try:
            return {"id": key, "ok": True, "data": fetch(key)}
        except Exception as exc:
            from conjira_cli.cli import _build_error_payload

            return {"id": key, "ok": False, **_build_error_payload(exc)}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, keys))
    return {
        "results": results,
        "count": len(results),
        "succeeded": sum(item["ok"] for item in results),
        "failed": sum(not item["ok"] for item in results),
    }


def heading_payload(page: dict[str, Any]) -> dict[str, Any]:
    body = (((page.get("body") or {}).get("storage") or {}).get("value")) or ""
    return {
        "page_id": page["id"],
        "version": (page.get("version") or {}).get("number"),
        "headings": list_headings(body),
    }


def search_results(args, client, *, jira=False):
    if args.limit < 1 or args.start < 0 or getattr(args, "max_items", 1000) < 1:
        raise ConfigError(
            "limit and max-items must be positive; start must be nonnegative."
        )
    start = args.start
    all_pages = getattr(args, "all", False)
    cap = getattr(args, "max_items", 1000) if all_pages else args.limit
    rows = []
    total = None
    more = False
    seen = set()
    while len(rows) < cap:
        if start in seen:
            raise ConfigError("Search returned a repeated pagination offset.")
        seen.add(start)
        limit = min(args.limit, cap - len(rows))
        if jira:
            result = client.search(
                jql=args.jql,
                limit=limit,
                start=start,
                fields=args.fields,
                expand=args.expand,
            )
            batch = result.get("issues", [])
            total = result.get("total")
            next_start = start + len(batch)
            more = next_start < total if total is not None else len(batch) >= limit
        else:
            result = client.search(
                cql=args.cql, limit=limit, start=start, expand=args.expand
            )
            batch = result.get("results", [])
            total = result.get("totalSize")
            next_start = start + len(batch)
            links = result.get("_links")
            more = (
                bool(links.get("next"))
                if isinstance(links, dict)
                else len(batch) >= int(result.get("limit") or limit)
            )
            if more and isinstance(links, dict):
                target = urllib.parse.urlsplit(
                    urllib.parse.urljoin(
                        client.base_url + "/rest/api/content/search", links["next"]
                    )
                )
                base_path = urllib.parse.urlsplit(client.base_url).path.rstrip("/")
                if url_origin(target.geturl()) != url_origin(
                    client.base_url
                ) or not target.path.startswith(base_path + "/rest/"):
                    raise ConfigError(
                        "Search pagination points outside the configured installation."
                    )
                values = urllib.parse.parse_qs(target.query)
                if "start" in values:
                    next_start = int(values["start"][0])
        if not all_pages and getattr(args, "raw", False):
            return result
        rows.extend(batch[: cap - len(rows)])
        start = next_start
        if not all_pages or not batch or not more:
            break
    if jira and getattr(args, "raw", False):
        payload = {"issues": rows}
    else:
        payload = client.summarize_search_results(rows)
    return {
        **payload,
        "count": len(rows),
        "start": args.start,
        "total": total,
        "has_more": more,
        "next_start": start if more else None,
    }
