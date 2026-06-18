from __future__ import annotations

import html
import re
from typing import Any, Dict, Iterable, Optional


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


def _truncate(value: str, limit: int = 240) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _webui_url(base_url: str, item: Dict[str, Any]) -> Optional[str]:
    links = item.get("_links") or {}
    webui = links.get("webui")
    if not webui:
        return None
    link_base = links.get("base") or base_url
    return "{0}{1}".format(link_base.rstrip("/"), webui)


def _parent_comment_id(item: Dict[str, Any]) -> Optional[str]:
    explicit_parent = item.get("parentCommentId")
    if explicit_parent:
        return str(explicit_parent)

    container = item.get("container") or {}
    if container.get("type") == "comment" and container.get("id"):
        return str(container["id"])

    for ancestor in reversed(item.get("ancestors") or []):
        if ancestor.get("type") == "comment" and ancestor.get("id"):
            return str(ancestor["id"])

    return None


def build_footer_comment_summary(
    *,
    base_url: str,
    page_id: str,
    page_title: str,
    page_url: str,
    raw_comments: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    comments: list[Dict[str, Any]] = []

    for item in raw_comments:
        history = item.get("history") or {}
        created_by = history.get("createdBy") or {}
        body_html = ((item.get("body") or {}).get("storage") or {}).get("value") or ""
        body_text = _html_to_text(body_html)
        parent_comment_id = _parent_comment_id(item)
        comments.append(
            {
                "id": item.get("id"),
                "status": item.get("status"),
                "title": item.get("title"),
                "parent_comment_id": parent_comment_id,
                "is_reply": parent_comment_id is not None,
                "body_text": body_text,
                "body_excerpt": _truncate(_single_line(body_text)),
                "created_at": history.get("createdDate"),
                "created_by": created_by.get("displayName") or "Unknown",
                "webui_url": _webui_url(base_url, item),
            }
        )

    reply_count = sum(1 for comment in comments if comment["is_reply"])

    return {
        "page_id": page_id,
        "page_title": page_title,
        "page_url": page_url,
        "total_comments": len(comments),
        "root_comment_count": len(comments) - reply_count,
        "reply_comment_count": reply_count,
        "comments": comments,
    }
