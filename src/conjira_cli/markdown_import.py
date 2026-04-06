from __future__ import annotations

import html
import os
import re
from typing import Optional


_LIST_ITEM_RE = re.compile(r"^(\s*)([-+*]|\d+\.)\s+(.*)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_HR_RE = re.compile(r"^ {0,3}([-*_])(?:\s*\1){2,}\s*$")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")
_INLINE_TOKEN_RE = re.compile(
    r"!\[\[(?P<obs_image>[^\]]+)\]\]"
    r"|\[\[(?P<obs_link>[^\]]+)\]\]"
    r"|!\[(?P<img_alt>[^\]]*)\]\((?P<img_target>[^)]+)\)"
    r"|\[(?P<link_text>[^\]]+)\]\((?P<link_target>[^)]+)\)"
    r"|`(?P<code>[^`]+)`"
)


def markdown_to_storage_html(markdown: str) -> str:
    markdown = _strip_frontmatter(markdown).replace("\r\n", "\n").replace("\r", "\n")
    lines = markdown.split("\n")
    html_parts, _ = _parse_blocks(lines, 0)
    return "".join(html_parts).strip()


def _strip_frontmatter(markdown: str) -> str:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return markdown

    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return "\n".join(lines[idx + 1 :])
    return markdown


def _parse_blocks(lines: list[str], start: int, *, stop_on_indent: Optional[int] = None) -> tuple[list[str], int]:
    parts: list[str] = []
    i = start

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        current_indent = _leading_spaces(line)
        if stop_on_indent is not None and current_indent < stop_on_indent:
            break

        stripped = line.strip()
        heading_match = _HEADING_RE.match(stripped)
        if heading_match:
            level = len(heading_match.group(1))
            parts.append(
                "<h{0}>{1}</h{0}>".format(level, _render_inline(heading_match.group(2).strip()))
            )
            i += 1
            continue

        if _HR_RE.match(stripped):
            parts.append("<hr />")
            i += 1
            continue

        if stripped.startswith("```"):
            block, i = _parse_fenced_code(lines, i)
            parts.append(block)
            continue

        if _is_table_start(lines, i):
            block, i = _parse_table(lines, i)
            parts.append(block)
            continue

        if _LIST_ITEM_RE.match(line):
            block, i = _parse_list(lines, i, current_indent)
            parts.append(block)
            continue

        if stripped.startswith(">"):
            block, i = _parse_blockquote(lines, i)
            parts.append(block)
            continue

        block, i = _parse_paragraph(lines, i, stop_on_indent=stop_on_indent)
        parts.append(block)

    return parts, i


def _parse_fenced_code(lines: list[str], start: int) -> tuple[str, int]:
    opening = lines[start].strip()
    fence = opening[:3]
    code_lines: list[str] = []
    i = start + 1
    while i < len(lines):
        if lines[i].strip().startswith(fence):
            return "<pre><code>{0}</code></pre>".format(html.escape("\n".join(code_lines))), i + 1
        code_lines.append(lines[i])
        i += 1
    return "<pre><code>{0}</code></pre>".format(html.escape("\n".join(code_lines))), i


def _parse_paragraph(
    lines: list[str],
    start: int,
    *,
    stop_on_indent: Optional[int] = None,
) -> tuple[str, int]:
    paragraph_lines: list[str] = []
    i = start
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            break
        current_indent = _leading_spaces(line)
        if stop_on_indent is not None and current_indent < stop_on_indent:
            break
        stripped = line.strip()
        if (
            i != start
            and (
                _HEADING_RE.match(stripped)
                or stripped.startswith("```")
                or _HR_RE.match(stripped)
                or _is_table_start(lines, i)
                or _LIST_ITEM_RE.match(line)
                or stripped.startswith(">")
            )
        ):
            break
        paragraph_lines.append(stripped)
        i += 1
    paragraph = " ".join(paragraph_lines).strip()
    return "<p>{0}</p>".format(_render_inline(paragraph)), i


def _parse_blockquote(lines: list[str], start: int) -> tuple[str, int]:
    quote_lines: list[str] = []
    i = start
    while i < len(lines):
        stripped = lines[i].lstrip()
        if not stripped.startswith(">"):
            break
        content = stripped[1:]
        if content.startswith(" "):
            content = content[1:]
        quote_lines.append(content)
        i += 1

    inner_parts, _ = _parse_blocks(quote_lines, 0)
    return "<blockquote>{0}</blockquote>".format("".join(inner_parts)), i


def _parse_list(lines: list[str], start: int, indent: int) -> tuple[str, int]:
    first_match = _LIST_ITEM_RE.match(lines[start])
    if first_match is None:
        raise ValueError("List parsing requires a list item")

    ordered = _is_ordered_marker(first_match.group(2))
    tag = "ol" if ordered else "ul"
    items: list[str] = []
    i = start

    while i < len(lines):
        match = _LIST_ITEM_RE.match(lines[i])
        if match is None:
            break

        current_indent = _leading_spaces(match.group(1))
        current_ordered = _is_ordered_marker(match.group(2))
        if current_indent < indent or current_ordered != ordered:
            break
        if current_indent > indent:
            nested, i = _parse_list(lines, i, current_indent)
            if items:
                items[-1] = items[-1].replace("</li>", nested + "</li>", 1)
            continue

        content_parts: list[str] = []
        inline_content = match.group(3).strip()
        if inline_content:
            content_parts.append(_render_inline(inline_content))
        i += 1

        while i < len(lines):
            next_line = lines[i]
            if not next_line.strip():
                i += 1
                break

            nested_match = _LIST_ITEM_RE.match(next_line)
            if nested_match is not None:
                nested_indent = _leading_spaces(nested_match.group(1))
                nested_ordered = _is_ordered_marker(nested_match.group(2))
                if nested_indent == indent and nested_ordered == ordered:
                    break
                if nested_indent > indent:
                    nested_html, i = _parse_list(lines, i, nested_indent)
                    content_parts.append(nested_html)
                    continue
                if nested_indent < indent:
                    break

            continuation_indent = _leading_spaces(next_line)
            if continuation_indent > indent:
                content_parts.append(" " + _render_inline(next_line.strip()))
                i += 1
                continue
            break

        items.append("<li>{0}</li>".format("".join(content_parts).strip()))

    return "<{0}>{1}</{0}>".format(tag, "".join(items)), i


def _parse_table(lines: list[str], start: int) -> tuple[str, int]:
    rows: list[list[str]] = []
    i = start

    header = _split_table_row(lines[i])
    separator = lines[i + 1] if i + 1 < len(lines) else ""
    has_header = _TABLE_SEPARATOR_RE.match(separator.strip()) is not None
    if has_header:
        rows.append(header)
        i += 2
    while i < len(lines):
        line = lines[i]
        if not line.strip() or "|" not in line:
            break
        if _TABLE_SEPARATOR_RE.match(line.strip()):
            i += 1
            continue
        rows.append(_split_table_row(line))
        i += 1

    if not rows:
        return "", i

    body_rows = rows[1:] if has_header else rows
    parts = ["<table><tbody>"]
    if has_header:
        parts.append(
            "<tr>{0}</tr>".format(
                "".join("<th>{0}</th>".format(_render_inline(cell)) for cell in rows[0])
            )
        )
    for row in body_rows:
        parts.append(
            "<tr>{0}</tr>".format(
                "".join("<td>{0}</td>".format(_render_inline(cell)) for cell in row)
            )
        )
    parts.append("</tbody></table>")
    return "".join(parts), i


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    if "|" not in lines[index]:
        return False
    return _TABLE_SEPARATOR_RE.match(lines[index + 1].strip()) is not None


def _leading_spaces(value: str) -> int:
    return len(value) - len(value.lstrip(" "))


def _is_ordered_marker(marker: str) -> bool:
    return marker.endswith(".") and marker[:-1].isdigit()


def _render_inline(text: str) -> str:
    parts: list[str] = []
    last_end = 0
    for match in _INLINE_TOKEN_RE.finditer(text):
        if match.start() > last_end:
            parts.append(_render_plain_segment(text[last_end : match.start()]))
        parts.append(_render_token(match))
        last_end = match.end()
    if last_end < len(text):
        parts.append(_render_plain_segment(text[last_end:]))
    return "".join(parts)


def _render_plain_segment(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"~~(.+?)~~", r"<del>\1</del>", escaped)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<em>\1</em>", escaped)
    return escaped


def _render_token(match: re.Match[str]) -> str:
    code = match.group("code")
    if code is not None:
        return "<code>{0}</code>".format(html.escape(code))

    obs_image = match.group("obs_image")
    if obs_image is not None:
        target, alias = _split_obsidian_target(obs_image)
        return _render_image_token(alias or target, target)

    obs_link = match.group("obs_link")
    if obs_link is not None:
        target, alias = _split_obsidian_target(obs_link)
        return _render_wikilink(alias or target, target)

    img_target = match.group("img_target")
    if img_target is not None:
        return _render_image_token(match.group("img_alt") or "", img_target)

    link_target = match.group("link_target")
    if link_target is not None:
        return _render_link_token(match.group("link_text") or link_target, link_target)

    return ""


def _split_obsidian_target(value: str) -> tuple[str, Optional[str]]:
    if "|" not in value:
        return value.strip(), None
    target, alias = value.split("|", 1)
    return target.strip(), alias.strip() or None


def _render_image_token(alt_text: str, target: str) -> str:
    target = target.strip().strip("<>")
    if _has_url_scheme(target):
        return '<ac:image><ri:url ri:value="{0}" /></ac:image>'.format(html.escape(target, quote=True))
    filename = html.escape(os.path.basename(target), quote=True)
    return '<ac:image><ri:attachment ri:filename="{0}" /></ac:image>'.format(filename)


def _render_link_token(text: str, target: str) -> str:
    target = target.strip().strip("<>")
    text = text.strip() or target
    if _has_url_scheme(target):
        return '<a href="{0}">{1}</a>'.format(
            html.escape(target, quote=True),
            _render_plain_segment(text),
        )
    filename = html.escape(os.path.basename(target), quote=True)
    return (
        '<ac:link><ri:attachment ri:filename="{0}" />'
        '<ac:plain-text-link-body><![CDATA[{1}]]></ac:plain-text-link-body></ac:link>'
    ).format(filename, text)


def _render_wikilink(text: str, target: str) -> str:
    target = target.strip()
    text = text.strip() or target
    if _looks_like_attachment(target):
        filename = html.escape(os.path.basename(target), quote=True)
        return (
            '<ac:link><ri:attachment ri:filename="{0}" />'
            '<ac:plain-text-link-body><![CDATA[{1}]]></ac:plain-text-link-body></ac:link>'
        ).format(filename, text)
    return (
        '<ac:link><ri:page ri:content-title="{0}" />'
        '<ac:plain-text-link-body><![CDATA[{1}]]></ac:plain-text-link-body></ac:link>'
    ).format(html.escape(target, quote=True), text)


def _has_url_scheme(value: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value))


def _looks_like_attachment(value: str) -> bool:
    basename = os.path.basename(value)
    if "." not in basename:
        return False
    extension = basename.rsplit(".", 1)[1].lower()
    return extension not in {"md", "markdown"}
