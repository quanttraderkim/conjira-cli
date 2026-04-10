from __future__ import annotations

import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import Any


_STRUCTURED_TABLE_KEY_HEADERS = {
    "category",
    "component",
    "feature",
    "field",
    "flow",
    "group",
    "item",
    "label",
    "name",
    "option",
    "screen",
    "section",
    "setting",
    "step",
    "title",
    "구분",
    "기능",
    "단계",
    "명칭",
    "분류",
    "설정",
    "섹션",
    "순서",
    "옵션",
    "이름",
    "항목명",
    "카테고리",
    "컴포넌트",
    "타이틀",
    "항목",
    "화면",
    "흐름",
    "필드",
}

_STRUCTURED_TABLE_CONTENT_HEADERS = {
    "content",
    "definition",
    "description",
    "detail",
    "details",
    "overview",
    "summary",
    "내용",
    "상세",
    "설명",
    "요약",
}

_CALLOUT_MACRO_NAMES = {"info", "note", "tip", "warning", "expand"}
_STATUS_COLOUR_ALIASES = {
    "blue": "blue",
    "green": "green",
    "grey": "grey",
    "gray": "grey",
    "purple": "purple",
    "red": "red",
    "yellow": "yellow",
}


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _clean_text(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("\xa0", " ")
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _collapse_inline(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _join_inline_pieces(pieces: list[str]) -> str:
    filtered = [piece for piece in pieces if piece]
    if not filtered:
        return ""
    joined = " ".join(filtered)
    joined = re.sub(r"\s+([,.;!?]|:(?!status\[))", r"\1", joined)
    joined = re.sub(r"\(\s+", "(", joined)
    joined = re.sub(r"\s+\)", ")", joined)
    joined = joined.replace(" \n ", "\n")
    joined = joined.replace("\n ", "\n")
    joined = joined.replace(" \n", "\n")
    return joined.strip()


def _normalize_table_header(value: str) -> str:
    value = _collapse_inline(value).lower()
    value = value.strip(":：")
    value = re.sub(r"\s+", " ", value)
    return value


def _escape_table_cell(value: str) -> str:
    return value.replace("|", "\\|").strip()


@dataclass
class MarkdownExporter:
    base_url: str
    page_id: str
    mermaid_macro_name: str | None = None

    def convert_page(self, page: dict[str, Any]) -> str:
        title = page.get("title") or "Untitled"
        source_url = page.get("webui_url") or ""
        version = page.get("version")
        parent_page_id = page.get("parent_page_id")
        page_kind = page.get("page_kind")
        child_count = page.get("child_count")
        body_html = page.get("body_html") or ""
        children = page.get("children") or []
        if page_kind == "hub" and children:
            body_md = self._render_hub_page(children)
        else:
            body_md = self.convert_fragment(body_html)

        parts = [
            "---",
            f'title: "{title.replace(chr(34), chr(39))}"',
            f"confluence_page_id: {self.page_id}",
            f"confluence_version: {version}",
        ]
        if parent_page_id:
            parts.append(f"confluence_parent_page_id: {parent_page_id}")
        if page_kind:
            parts.append(f"confluence_page_kind: {page_kind}")
        if child_count:
            parts.append(f"confluence_child_count: {child_count}")
        parts.extend(
            [
            f"source_url: {source_url}",
            f"exported_at: {datetime.now().astimezone().isoformat(timespec='seconds')}",
            "---",
            "",
            f"# {title}",
            "",
            f"Source: {source_url}",
            "",
            body_md.strip(),
            "",
            ]
        )
        return "\n".join(parts)

    def _render_hub_page(self, children: list[dict[str, Any]]) -> str:
        lines = [
            "> [!INFO] This is a Confluence hub/index page.",
            "> The main content lives in the child pages listed below.",
            "",
            "## Child pages",
            "",
            "| Title | Page ID | Link |",
            "| --- | --- | --- |",
        ]
        for child in children:
            title = _escape_table_cell(child.get("title") or "Untitled")
            page_id = _escape_table_cell(str(child.get("id") or ""))
            url = child.get("webui_url") or ""
            link = f"[Open]({url})" if url else ""
            lines.append(f"| {title} | {page_id} | {link} |")
        lines.append("")
        return "\n".join(lines)

    def convert_fragment(self, body_html: str) -> str:
        wrapped = (
            '<root xmlns:ac="urn:ac" xmlns:ri="urn:ri">'
            + body_html
            + "</root>"
        )
        try:
            root = ET.fromstring(wrapped)
            rendered = self._render_blocks(list(root), indent=0)
            return _clean_text(self._postprocess_markdown(rendered)) + "\n"
        except ET.ParseError:
            return _clean_text(re.sub(r"<[^>]+>", "", body_html)) + "\n"

    def _render_blocks(self, elements: list[ET.Element], *, indent: int) -> str:
        parts: list[str] = []
        for elem in elements:
            parts.append(self._render_block(elem, indent=indent))
            if elem.tail and _collapse_inline(elem.tail):
                parts.append(_collapse_inline(elem.tail) + "\n")
        return "".join(parts)

    def _render_block(self, elem: ET.Element, *, indent: int) -> str:
        name = _local_name(elem.tag)
        if name == "structured-macro":
            macro_name = elem.attrib.get("{urn:ac}name")
            if macro_name == "toc":
                return ""
            if self.mermaid_macro_name and macro_name == self.mermaid_macro_name:
                return self._render_mermaid_macro(elem)
            if macro_name == "status":
                return self._render_status_token(elem) + "\n\n"
            if macro_name in _CALLOUT_MACRO_NAMES:
                return self._render_callout_macro(elem, macro_name)
            return self._render_children(elem, indent=indent)
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(name[1])
            text = self._extract_plain_text(elem)
            return f"{'#' * level} {text}\n\n" if text else ""
        if name == "p":
            text = self._render_inline_container(elem).strip()
            return f"{text}\n\n" if text else "\n"
        if name == "hr":
            return "---\n\n"
        if name == "ul":
            return self._render_list(elem, ordered=False, indent=indent) + "\n"
        if name == "ol":
            return self._render_list(elem, ordered=True, indent=indent) + "\n"
        if name == "table":
            return self._render_table(elem) + "\n\n"
        if name == "pre":
            text = "".join(elem.itertext()).strip("\n")
            return f"```\n{text}\n```\n\n" if text else ""
        if name == "image":
            return self._render_image(elem)
        if name in {"div", "tbody", "thead", "tfoot", "colgroup", "tr"}:
            return self._render_blocks(list(elem), indent=indent)
        if name in {"td", "th"}:
            return self._flatten_cell(elem)
        if name == "br":
            return "\n"
        return self._render_children(elem, indent=indent)

    def _render_children(self, elem: ET.Element, *, indent: int) -> str:
        return self._render_blocks(list(elem), indent=indent)

    def _render_inline_container(self, elem: ET.Element) -> str:
        pieces: list[str] = []
        if elem.text:
            pieces.append(_collapse_inline(elem.text))
        for child in list(elem):
            pieces.append(self._render_inline(child))
            if child.tail:
                pieces.append(_collapse_inline(child.tail))
        return _join_inline_pieces(pieces)

    def _extract_plain_text(self, elem: ET.Element) -> str:
        pieces = [_collapse_inline(text) for text in elem.itertext()]
        return _join_inline_pieces([piece for piece in pieces if piece])

    def _render_inline(self, elem: ET.Element) -> str:
        name = _local_name(elem.tag)
        if name in {"strong", "b"}:
            if self._contains_emphasis_child(elem):
                return self._extract_plain_text(elem)
            text = self._render_inline_container(elem)
            return f"**{text}**" if text else ""
        if name in {"em", "i"}:
            if self._contains_emphasis_child(elem):
                return self._extract_plain_text(elem)
            text = self._render_inline_container(elem)
            return f"*{text}*" if text else ""
        if name == "code":
            text = self._render_inline_container(elem)
            return f"`{text}`" if text else ""
        if name == "br":
            return "\n"
        if name == "a":
            text = self._render_inline_container(elem) or elem.attrib.get("href", "")
            href = elem.attrib.get("href", "")
            return f"[{text}]({href})" if href else text
        if name == "image":
            return self._render_image(elem).strip()
        if name == "inline-comment-marker":
            return self._render_inline_container(elem)
        if name == "attachment":
            filename = elem.attrib.get("{urn:ri}filename", "")
            return filename
        if name == "structured-macro":
            macro_name = elem.attrib.get("{urn:ac}name")
            if macro_name == "status":
                return self._render_status_token(elem)
            return ""
        if name in {"ul", "ol", "table"}:
            return "\n" + self._render_block(elem, indent=1).strip() + "\n"
        return self._render_inline_container(elem)

    def _render_list(self, elem: ET.Element, *, ordered: bool, indent: int) -> str:
        lines: list[str] = []
        number = 1
        for child in list(elem):
            if _local_name(child.tag) != "li":
                continue
            prefix = f"{number}. " if ordered else "- "
            number += 1

            inline_parts: list[str] = []
            nested_parts: list[str] = []

            if child.text and _collapse_inline(child.text):
                inline_parts.append(_collapse_inline(child.text))

            for grandchild in list(child):
                grandchild_name = _local_name(grandchild.tag)
                if grandchild_name in {"ul", "ol", "table"}:
                    nested_text = self._render_block(grandchild, indent=indent + 1).rstrip()
                    if not nested_text:
                        continue
                    if grandchild_name == "table":
                        nested_parts.append(nested_text)
                    else:
                        nested_parts.append(
                            self._indent_text(
                                nested_text,
                                spaces=(indent + 1) * 2,
                            )
                        )
                else:
                    inline_parts.append(self._render_inline(grandchild))
                if grandchild.tail and _collapse_inline(grandchild.tail):
                    inline_parts.append(_collapse_inline(grandchild.tail))

            line = (" " * (indent * 2)) + prefix + "".join(inline_parts).strip()
            lines.append(line.rstrip())
            for nested in nested_parts:
                if nested:
                    lines.append(nested)
        return "\n".join(line for line in lines if line.strip())

    def _render_table(self, elem: ET.Element) -> str:
        row_elements = self._extract_table_rows(elem)
        if not row_elements:
            return ""

        headers = [self._flatten_cell(cell) for cell in row_elements[0]]
        if self._is_structured_table(headers):
            return self._render_structured_table(headers, row_elements[1:])

        rows = [
            [self._flatten_cell(cell) for cell in row]
            for row in row_elements
        ]

        width = max(len(row) for row in rows)
        normalized = [row + [""] * (width - len(row)) for row in rows]
        header = normalized[0]
        body = normalized[1:] if len(normalized) > 1 else []
        separator = ["---"] * width

        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(separator) + " |",
        ]
        for row in body:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)

    def _extract_table_rows(self, elem: ET.Element) -> list[list[ET.Element]]:
        rows: list[list[ET.Element]] = []
        for child in list(elem):
            child_name = _local_name(child.tag)
            if child_name == "tr":
                rows.append(self._extract_cells(child))
                continue
            if child_name in {"tbody", "thead", "tfoot"}:
                for row in list(child):
                    if _local_name(row.tag) == "tr":
                        rows.append(self._extract_cells(row))
        return [row for row in rows if row]

    @staticmethod
    def _extract_cells(row: ET.Element) -> list[ET.Element]:
        return [
            cell for cell in list(row)
            if _local_name(cell.tag) in {"th", "td"}
        ]

    @staticmethod
    def _is_structured_table(headers: list[str]) -> bool:
        if len(headers) < 2:
            return False
        first = _normalize_table_header(headers[0])
        second = _normalize_table_header(headers[1])
        return (
            first in _STRUCTURED_TABLE_KEY_HEADERS
            and second in _STRUCTURED_TABLE_CONTENT_HEADERS
        )

    def _render_structured_table(
        self,
        headers: list[str],
        row_elements: list[list[ET.Element]],
    ) -> str:
        parts: list[str] = []
        extra_headers = headers[2:]
        for row in row_elements:
            if not row:
                continue
            title = self._flatten_cell(row[0]) or "Item"
            parts.append(f"#### {title}\n\n")

            if len(row) > 1:
                content = self._render_cell_content(row[1]).strip()
                if content:
                    parts.append(content + "\n\n")

            for idx, header in enumerate(extra_headers, start=2):
                if idx >= len(row):
                    continue
                content = self._render_cell_content(row[idx]).strip()
                if not content:
                    continue
                label = header.strip() or f"Note {idx - 1}"
                if "\n" in content or content.startswith(("-", "|", "![", "#", "```")):
                    parts.append(f"**{label}**\n\n{content}\n\n")
                else:
                    parts.append(f"**{label}:** {content}\n\n")
        return "".join(parts).strip()

    def _render_cell_content(self, elem: ET.Element) -> str:
        blocks: list[str] = []
        inline_pieces: list[str] = []

        def flush_inline() -> None:
            joined = _join_inline_pieces(inline_pieces)
            if joined:
                blocks.append(joined)
            inline_pieces.clear()

        if elem.text and _collapse_inline(elem.text):
            inline_pieces.append(_collapse_inline(elem.text))

        for child in list(elem):
            child_name = _local_name(child.tag)
            if child_name in {"p", "ul", "ol", "table", "pre", "div", "image"} or child_name.startswith("h"):
                flush_inline()
                block = self._render_block(child, indent=0).strip()
                if block:
                    blocks.append(block)
            elif child_name == "br":
                flush_inline()
            else:
                inline_pieces.append(self._render_inline(child))
            if child.tail and _collapse_inline(child.tail):
                inline_pieces.append(_collapse_inline(child.tail))

        flush_inline()
        return "\n\n".join(block for block in blocks if block).strip()

    def _flatten_cell(self, elem: ET.Element) -> str:
        pieces: list[str] = []
        if elem.text and _collapse_inline(elem.text):
            pieces.append(_collapse_inline(elem.text))
        for child in list(elem):
            child_name = _local_name(child.tag)
            if child_name in {"ul", "ol"}:
                list_text = self._render_block(child, indent=0).strip().replace("\n", "<br>")
                pieces.append(list_text)
            elif child_name == "table":
                table_text = self._render_table(child).replace("\n", "<br>")
                pieces.append(table_text)
            else:
                pieces.append(self._render_inline(child))
            if child.tail and _collapse_inline(child.tail):
                pieces.append(_collapse_inline(child.tail))
        joined = _join_inline_pieces(pieces)
        joined = joined.replace("|", "\\|")
        joined = joined.replace("\n", "<br>")
        joined = re.sub(r"\s{2,}", " ", joined)
        joined = re.sub(r"^(<br>\s*)+$", "", joined)
        return joined.strip()

    def _render_image(self, elem: ET.Element) -> str:
        attachment_name = None
        for child in elem.iter():
            if _local_name(child.tag) == "attachment":
                attachment_name = child.attrib.get("{urn:ri}filename")
                break
        if not attachment_name:
            return ""
        quoted = urllib.parse.quote(attachment_name)
        url = "{0}/download/attachments/{1}/{2}".format(
            self.base_url.rstrip("/"),
            self.page_id,
            quoted,
        )
        return f"![{attachment_name}]({url})\n\n"

    def _render_mermaid_macro(self, elem: ET.Element) -> str:
        text = self._extract_macro_plain_text_body(elem).strip("\n")
        return f"```mermaid\n{text}\n```\n\n" if text else "```mermaid\n```\n\n"

    def _render_callout_macro(self, elem: ET.Element, macro_name: str) -> str:
        title = self._extract_macro_parameter(elem, "title")
        rich_body = self._extract_macro_rich_text_body(elem).strip()
        label = "EXPAND" if macro_name == "expand" else macro_name.upper()
        header = f"> [!{label}]"
        if title:
            header += f" {title}"

        if not rich_body:
            return header + "\n\n"

        quoted_body = self._prefix_blockquote(rich_body)
        return f"{header}\n{quoted_body}\n\n"

    def _render_status_token(self, elem: ET.Element) -> str:
        title = self._extract_macro_parameter(elem, "title")
        colour = self._extract_macro_parameter(elem, "colour") or self._extract_macro_parameter(elem, "color")
        normalized_colour = self._normalize_status_colour(colour)
        return f":status[{title}]{{color={normalized_colour}}}"

    @staticmethod
    def _extract_macro_plain_text_body(elem: ET.Element) -> str:
        for child in elem.iter():
            if _local_name(child.tag) == "plain-text-body":
                return child.text or ""
        return ""

    def _extract_macro_rich_text_body(self, elem: ET.Element) -> str:
        for child in list(elem):
            if _local_name(child.tag) == "rich-text-body":
                return self._render_blocks(list(child), indent=0)
        return ""

    @staticmethod
    def _extract_macro_parameter(elem: ET.Element, param_name: str) -> str:
        for child in list(elem):
            if _local_name(child.tag) != "parameter":
                continue
            if child.attrib.get("{urn:ac}name") != param_name:
                continue
            return _collapse_inline("".join(child.itertext()))
        return ""

    @staticmethod
    def _normalize_status_colour(value: str) -> str:
        stripped = value.strip()
        if not stripped:
            return "grey"
        return _STATUS_COLOUR_ALIASES.get(stripped.lower(), stripped.lower())

    @staticmethod
    def _contains_emphasis_child(elem: ET.Element) -> bool:
        for child in elem.iter():
            if child is elem:
                continue
            if _local_name(child.tag) in {"strong", "b", "em", "i"}:
                return True
        return False

    def _postprocess_markdown(self, value: str) -> str:
        value = re.sub(r'(?m)^[ \t]+(?=\|)', '', value)
        value = re.sub(r'(?<!\n)(!\[[^\]]+\]\([^)]+\))', r'\n\n\1', value)
        value = re.sub(r'(?m)^(\*\*[^:\n]+:\*\* .+?)\n\n(!\[)', r'\1\n\n\2', value)
        value = re.sub(r'(?m)^([ \t]*)-\s+([^\n]*?)\n\n(!\[)', r'\1- \2\n\n\3', value)
        value = re.sub(r'(?m)^([ \t]*)\*\*([^:\n]+):\*\*\s*([^\n]+?)\n\n(!\[)', r'\1**\2:** \3\n\n\4', value)

        fixed_lines: list[str] = []
        for line in value.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("|"):
                fixed_lines.append(line.rstrip())
                continue

            if line.count("**") % 2 == 1:
                line = line.replace("*", "")
            elif line.count("*") % 2 == 1:
                line = line.replace("*", "")

            if "![" in line and not stripped.startswith("!["):
                line = line.replace("![", "\n\n![", 1)
            line = re.sub(r'^ {10,}(- )', '        \\1', line)
            line = re.sub(r'^ {12,}(\d+\. )', '        \\1', line)
            fixed_lines.append(line.rstrip())

        value = "\n".join(fixed_lines)
        value = re.sub(r'\n{3,}', '\n\n', value)
        return value

    @staticmethod
    def _indent_text(value: str, *, spaces: int) -> str:
        prefix = " " * spaces
        return "\n".join(prefix + line if line else line for line in value.splitlines())

    @staticmethod
    def _prefix_blockquote(value: str) -> str:
        lines = value.rstrip().splitlines()
        return "\n".join("> " + line if line else ">" for line in lines)
