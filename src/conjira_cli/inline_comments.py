from __future__ import annotations

import html
import re
from collections import Counter
from datetime import datetime
from typing import Any, Dict, Iterable


_STATUS_ORDER = {"open": 0, "dangling": 1, "resolved": 2}


def _html_to_text(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"</p\s*>", "\n\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<li[^>]*>", "- ", value, flags=re.IGNORECASE)
    value = re.sub(r"</li\s*>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value).replace("\xa0", " ")
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    return value.strip()


def _single_line(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _truncate(value: str, limit: int = 160) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _thread_status(comments: list[Dict[str, Any]]) -> str:
    if any(comment["status"] == "open" for comment in comments):
        return "open"
    if any(comment["status"] == "dangling" for comment in comments):
        return "dangling"
    if any(comment["status"] == "resolved" for comment in comments):
        return "resolved"
    return comments[-1]["status"] if comments else "unknown"


def build_inline_comment_summary(
    *,
    base_url: str,
    page_id: str,
    page_title: str,
    page_url: str,
    raw_comments: Iterable[Dict[str, Any]],
    status_filter: str = "all",
) -> Dict[str, Any]:
    normalized_comments: list[Dict[str, Any]] = []
    for item in raw_comments:
        history = item.get("history") or {}
        created_by = history.get("createdBy") or {}
        extensions = item.get("extensions") or {}
        inline_properties = extensions.get("inlineProperties") or {}
        resolution = extensions.get("resolution") or {}
        links = item.get("_links") or {}
        body_html = ((item.get("body") or {}).get("storage") or {}).get("value") or ""
        body_text = _html_to_text(body_html)
        webui = links.get("webui") or ""
        normalized_comments.append(
            {
                "id": item.get("id"),
                "status": resolution.get("status") or "unknown",
                "selection": (inline_properties.get("originalSelection") or "").strip(),
                "marker_ref": (inline_properties.get("markerRef") or "").strip(),
                "body_text": body_text,
                "body_excerpt": _truncate(_single_line(body_text)),
                "created_at": history.get("createdDate"),
                "created_by": created_by.get("displayName") or "Unknown",
                "webui_url": "{0}{1}".format(base_url.rstrip("/"), webui) if webui else None,
            }
        )

    all_threads: list[Dict[str, Any]] = []
    current_thread: Dict[str, Any] | None = None
    thread_by_marker: dict[str, Dict[str, Any]] = {}

    for comment in normalized_comments:
        marker_ref = comment["marker_ref"]
        selection = comment["selection"]
        if marker_ref or selection:
            if marker_ref and marker_ref in thread_by_marker:
                thread = thread_by_marker[marker_ref]
            else:
                thread = {
                    "thread_id": marker_ref or "selection-{0}".format(comment["id"]),
                    "selection": selection or "(No quoted selection)",
                    "marker_ref": marker_ref or None,
                    "comments": [],
                }
                all_threads.append(thread)
                if marker_ref:
                    thread_by_marker[marker_ref] = thread
            current_thread = thread
        elif current_thread is None:
            current_thread = {
                "thread_id": "orphan-{0}".format(comment["id"]),
                "selection": "(Reply without quoted selection)",
                "marker_ref": None,
                "comments": [],
            }
            all_threads.append(current_thread)

        current_thread["comments"].append(comment)

    for thread in all_threads:
        comments = thread["comments"]
        latest_comment = max(
            comments,
            key=lambda comment: comment["created_at"] or "",
        )
        participants = sorted(
            {comment["created_by"] for comment in comments if comment["created_by"]}
        )
        thread["status"] = _thread_status(comments)
        thread["comment_count"] = len(comments)
        thread["participants"] = participants
        thread["latest_comment_at"] = latest_comment["created_at"]
        thread["latest_comment_excerpt"] = latest_comment["body_excerpt"]
        thread["latest_comment_url"] = latest_comment["webui_url"]

    selected_threads = all_threads
    if status_filter != "all":
        selected_threads = [
            thread
            for thread in all_threads
            if any(comment["status"] == status_filter for comment in thread["comments"])
        ]

    selected_threads.sort(
        key=lambda thread: (
            _STATUS_ORDER.get(thread["status"], 99),
            thread["selection"].lower(),
        )
    )

    matching_comment_count = len(normalized_comments)
    if status_filter != "all":
        matching_comment_count = sum(
            1 for comment in normalized_comments if comment["status"] == status_filter
        )

    selected_comments = [
        comment
        for thread in selected_threads
        for comment in thread["comments"]
    ]

    status_counts = Counter(comment["status"] for comment in selected_comments)
    thread_status_counts = Counter(thread["status"] for thread in selected_threads)
    anchored_comment_count = sum(
        1 for comment in selected_comments if comment["marker_ref"] or comment["selection"]
    )
    reply_comment_count = len(selected_comments) - anchored_comment_count

    return {
        "page_id": page_id,
        "page_title": page_title,
        "page_url": page_url,
        "status_filter": status_filter,
        "total_comments": len(selected_comments),
        "all_comment_count": len(normalized_comments),
        "matching_comment_count": matching_comment_count,
        "anchored_comment_count": anchored_comment_count,
        "reply_comment_count": reply_comment_count,
        "thread_count": len(selected_threads),
        "open_thread_count": thread_status_counts.get("open", 0),
        "status_counts": dict(status_counts),
        "thread_status_counts": dict(thread_status_counts),
        "threads": selected_threads,
    }


def render_inline_comment_summary_markdown(summary: Dict[str, Any]) -> str:
    page_title = summary["page_title"]
    page_url = summary["page_url"]
    status_counts = summary["status_counts"]
    threads = summary["threads"]
    exported_at = datetime.now().astimezone().isoformat(timespec="seconds")

    parts = [
        "---",
        'title: "{0}"'.format(
            "{0} - Inline Comment Summary".format(page_title).replace('"', "'")
        ),
        "confluence_page_id: {0}".format(summary["page_id"]),
        "source_url: {0}".format(page_url),
        "exported_at: {0}".format(exported_at),
        "---",
        "",
        "# {0} - Inline Comment Summary".format(page_title),
        "",
        "Source page: {0}".format(page_url),
        "",
        "## Quick Summary",
        "",
        "- Total inline comments fetched: {0}".format(summary["all_comment_count"]),
        "- Matching comments for filter `{0}`: {1}".format(
            summary["status_filter"],
            summary["matching_comment_count"],
        ),
        "- Anchored comments: {0}".format(summary["anchored_comment_count"]),
        "- Reply comments: {0}".format(summary["reply_comment_count"]),
        "- Threads to review: {0}".format(summary["thread_count"]),
        "- Open threads: {0}".format(summary["open_thread_count"]),
        "- Comment status distribution: open {0}, resolved {1}, dangling {2}".format(
            status_counts.get("open", 0),
            status_counts.get("resolved", 0),
            status_counts.get("dangling", 0),
        ),
        "",
        "## Threads",
        "",
    ]

    if not threads:
        parts.append("- No inline comment threads matched the requested filter.")
        return "\n".join(parts).strip() + "\n"

    grouped_threads = {
        "open": [thread for thread in threads if thread["status"] == "open"],
        "dangling": [thread for thread in threads if thread["status"] == "dangling"],
        "resolved": [thread for thread in threads if thread["status"] == "resolved"],
        "other": [
            thread
            for thread in threads
            if thread["status"] not in {"open", "dangling", "resolved"}
        ],
    }

    section_titles = {
        "open": "Open",
        "dangling": "Dangling",
        "resolved": "Resolved",
        "other": "Other",
    }

    for key in ("open", "dangling", "resolved", "other"):
        matching_threads = grouped_threads[key]
        if not matching_threads:
            continue
        parts.append("### {0}".format(section_titles[key]))
        parts.append("")
        for thread in matching_threads:
            parts.append("- `{0}`".format(thread["selection"]))
            parts.append(
                "  Status: {0} | Comments: {1} | Participants: {2}".format(
                    thread["status"],
                    thread["comment_count"],
                    ", ".join(thread["participants"]) if thread["participants"] else "Unknown",
                )
            )
            if thread["latest_comment_at"]:
                parts.append("  Latest comment at: {0}".format(thread["latest_comment_at"]))
            if thread["latest_comment_excerpt"]:
                parts.append("  Latest note: {0}".format(thread["latest_comment_excerpt"]))
            if thread["latest_comment_url"]:
                parts.append("  Link: {0}".format(thread["latest_comment_url"]))
            parts.append("")

    return "\n".join(parts).strip() + "\n"
