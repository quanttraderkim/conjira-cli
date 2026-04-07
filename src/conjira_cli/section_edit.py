from __future__ import annotations

import copy
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass


ET.register_namespace("ac", "urn:ac")
ET.register_namespace("ri", "urn:ri")


_WRAPPED_ROOT_PREFIX = '<root xmlns:ac="urn:ac" xmlns:ri="urn:ri">'


class SectionEditError(ValueError):
    pass


@dataclass
class SectionReplacementResult:
    heading: str
    matched_heading: str
    heading_level: int
    old_section_html: str
    new_section_html: str
    updated_body_html: str


def replace_section_html(
    body_html: str,
    *,
    heading: str,
    replacement_html: str,
) -> SectionReplacementResult:
    root = _parse_fragment(body_html)
    children = list(root)
    normalized_target = _normalize_heading(heading)

    matches: list[tuple[int, ET.Element, int]] = []
    for index, child in enumerate(children):
        heading_level = _heading_level(child)
        if heading_level is None:
            continue
        rendered_heading = _element_text(child)
        if _normalize_heading(rendered_heading) == normalized_target:
            matches.append((index, child, heading_level))

    if not matches:
        raise SectionEditError(
            'replace-section target heading "{0}" was not found.'.format(heading)
        )
    if len(matches) > 1:
        raise SectionEditError(
            'replace-section target heading "{0}" is ambiguous because it appears multiple times.'.format(
                heading
            )
        )

    match_index, match_elem, match_level = matches[0]
    end_index = len(children)
    for index in range(match_index + 1, len(children)):
        next_level = _heading_level(children[index])
        if next_level is not None and next_level <= match_level:
            end_index = index
            break

    old_section_children = children[match_index + 1 : end_index]
    old_section_html = _serialize_elements(old_section_children)

    new_root = _parse_fragment(replacement_html)
    new_children = [copy.deepcopy(child) for child in list(new_root)]

    for child in old_section_children:
        root.remove(child)
    insert_at = match_index + 1
    for offset, child in enumerate(new_children):
        root.insert(insert_at + offset, child)

    return SectionReplacementResult(
        heading=heading,
        matched_heading=_element_text(match_elem),
        heading_level=match_level,
        old_section_html=old_section_html,
        new_section_html=_serialize_elements(new_children),
        updated_body_html=_serialize_root(root),
    )


def _parse_fragment(fragment_html: str) -> ET.Element:
    wrapped = _WRAPPED_ROOT_PREFIX + fragment_html + "</root>"
    try:
        return ET.fromstring(wrapped)
    except ET.ParseError as exc:
        raise SectionEditError("Failed to parse Confluence storage HTML fragment.") from exc


def _serialize_root(root: ET.Element) -> str:
    return _serialize_elements(list(root))


def _serialize_elements(elements: list[ET.Element]) -> str:
    return "".join(ET.tostring(element, encoding="unicode") for element in elements).strip()


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _heading_level(element: ET.Element) -> int | None:
    name = _local_name(element.tag)
    if re.fullmatch(r"h[1-6]", name):
        return int(name[1])
    return None


def _element_text(element: ET.Element) -> str:
    return _normalize_heading("".join(element.itertext()))


def _normalize_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
