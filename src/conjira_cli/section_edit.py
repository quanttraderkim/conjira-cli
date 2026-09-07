from __future__ import annotations

import copy
import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass


ET.register_namespace("ac", "urn:ac")
ET.register_namespace("ri", "urn:ri")


_WRAPPED_ROOT_PREFIX = '<root xmlns:ac="urn:ac" xmlns:ri="urn:ri">'
_CDATA_RE = re.compile(r"<!\[CDATA\[.*?\]\]>", re.DOTALL)


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


@dataclass
class HeadingInsertionResult:
    heading: str
    matched_heading: str
    heading_level: int
    inserted_html: str
    updated_body_html: str


class _CdataVault:
    """Hide CDATA sections from the XML parser and restore them after serialization.

    ElementTree folds ``<![CDATA[...]]>`` into ordinary text and writes it back
    escaped, which Confluence no longer treats as a plain-text macro body.
    """

    def __init__(self) -> None:
        self._token = "conjira-cdata-" + uuid.uuid4().hex
        self._sections: list[str] = []
        self._placeholder_re = re.compile(re.escape(self._token) + r"-(\d+)-")

    def protect(self, html: str) -> str:
        def _stash(match: re.Match[str]) -> str:
            self._sections.append(match.group(0))
            return "{0}-{1}-".format(self._token, len(self._sections) - 1)

        return _CDATA_RE.sub(_stash, html)

    def restore(self, html: str) -> str:
        return self._placeholder_re.sub(lambda match: self._sections[int(match.group(1))], html)


def replace_section_html(
    body_html: str,
    *,
    heading: str,
    replacement_html: str,
) -> SectionReplacementResult:
    vault = _CdataVault()
    root = _parse_fragment(vault.protect(body_html))
    children = list(root)
    match_index, match_elem, match_level = _find_unique_heading(
        children,
        heading=heading,
        action_name="replace-section",
    )
    end_index = len(children)
    for index in range(match_index + 1, len(children)):
        next_level = _heading_level(children[index])
        if next_level is not None and next_level <= match_level:
            end_index = index
            break

    old_section_children = children[match_index + 1 : end_index]
    old_section_html = _serialize_elements(old_section_children)

    new_root = _parse_fragment(vault.protect(replacement_html))
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
        old_section_html=vault.restore(old_section_html),
        new_section_html=vault.restore(_serialize_elements(new_children)),
        updated_body_html=vault.restore(_serialize_root(root)),
    )


def insert_after_heading_html(
    body_html: str,
    *,
    heading: str,
    inserted_html: str,
) -> HeadingInsertionResult:
    vault = _CdataVault()
    root = _parse_fragment(vault.protect(body_html))
    children = list(root)
    match_index, match_elem, match_level = _find_unique_heading(
        children,
        heading=heading,
        action_name="insert-after-heading",
    )

    new_root = _parse_fragment(vault.protect(inserted_html))
    new_children = [copy.deepcopy(child) for child in list(new_root)]

    insert_at = match_index + 1
    for offset, child in enumerate(new_children):
        root.insert(insert_at + offset, child)

    return HeadingInsertionResult(
        heading=heading,
        matched_heading=_element_text(match_elem),
        heading_level=match_level,
        inserted_html=vault.restore(_serialize_elements(new_children)),
        updated_body_html=vault.restore(_serialize_root(root)),
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


def _find_unique_heading(
    children: list[ET.Element],
    *,
    heading: str,
    action_name: str,
) -> tuple[int, ET.Element, int]:
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
            '{0} target heading "{1}" was not found.'.format(action_name, heading)
        )
    if len(matches) > 1:
        raise SectionEditError(
            '{0} target heading "{1}" is ambiguous because it appears multiple times.'.format(
                action_name,
                heading,
            )
        )
    return matches[0]


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
