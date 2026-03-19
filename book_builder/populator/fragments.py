"""XML fragment sanitation and extraction utilities.

These helpers normalize converter output into robust, insertable fragment
blocks, including recovery paths for malformed XML and separation of exercise
content from narrative content.
"""

from __future__ import annotations

import copy
import random
import re
import string
import lxml.etree as ET

from slugify import slugify

try:
    import lxml.etree as LET
except Exception:  # pragma: no cover - optional runtime dependency
    LET = None

from book_builder.populator.models import (
    ALLOWED_XML_TAGS,
    CP1252_CONTROL_MAP,
    INVALID_XML_CHARS_RE,
    SECTION_TAGS,
    local_name,
    text_or_empty,
)
from book_builder.populator.scoped_ids import ScopedIdRegistry


ID_ELIGIBLE_TAGS = {
    "section",
    "subsection",
    "subsubsection",
    "introduction",
    "paragraphs",
    "exercise",
    "exercisegroup",
    "exercises",
    "example",
    "figure",
    "table",
    "tabular",
    "insight",
    "objectives",
    "li",
    "ol",
    "ul",
}

XML_ID_ATTR = "{http://www.w3.org/XML/1998/namespace}id"

_ID_CHARS = string.digits + string.ascii_lowercase + string.ascii_uppercase


def _random_id_token(length: int = 10) -> str:
    return "".join(random.choice(_ID_CHARS) for _ in range(length))


def sanitize_xml_text(xml: str) -> str:
    """Repair cp1252 control characters and invalid XML control codes."""
    if not xml:
        return xml

    if any(0x7F <= ord(ch) <= 0x9F for ch in xml):
        xml = "".join(CP1252_CONTROL_MAP.get(ord(ch), ch) for ch in xml)

    return INVALID_XML_CHARS_RE.sub("", xml)


def section_to_paragraph_title_block(section_element: ET.Element) -> ET.Element:
    paragraphs = ET.Element("paragraphs")
    title_text = section_element.findtext("title", default="").strip()
    title_node = ET.SubElement(paragraphs, "title")
    title_node.text = title_text
    return paragraphs


def expand_section_markers(element: ET.Element) -> list[ET.Element]:
    tag = local_name(element.tag)
    if tag in SECTION_TAGS:
        expanded: list[ET.Element] = [section_to_paragraph_title_block(element)]
        for child in list(element):
            if local_name(child.tag) == "title":
                continue
            expanded.extend(expand_section_markers(copy.deepcopy(child)))
        return expanded

    index = 0
    while index < len(element):
        child = element[index]
        child_tag = local_name(child.tag)
        if child_tag in SECTION_TAGS:
            replacements = expand_section_markers(copy.deepcopy(child))
            element.remove(child)
            for offset, replacement in enumerate(replacements):
                element.insert(index + offset, replacement)
            index += len(replacements)
        else:
            nested = expand_section_markers(child)
            if len(nested) == 1 and nested[0] is child:
                index += 1
            else:
                element.remove(child)
                for offset, replacement in enumerate(nested):
                    element.insert(index + offset, replacement)
                index += len(nested)

    return [element]


def _recover_xml_with_lxml(xml: str) -> str | None:
    """Attempt lossy XML recovery using lxml when strict parsing fails."""
    if LET is None:
        return None

    try:
        parser = LET.XMLParser(recover=True)
        recovered_root = LET.fromstring(xml.encode("utf-8"), parser=parser)
    except Exception:
        return None

    if recovered_root is None:
        return None
    return LET.tostring(recovered_root, encoding="unicode")


def _extract_fragment_xml_strict(converted_xml: str) -> list[str]:
    """Strictly parse converted XML and return cleaned top-level fragment blocks."""
    root = ET.fromstring(converted_xml)
    fragments: list[ET.Element] = []

    for child in list(root):
        tag = local_name(child.tag)
        if tag == "title":
            continue
        if tag == "introduction":
            for intro_child in list(child):
                fragments.append(copy.deepcopy(intro_child))
        else:
            fragments.append(copy.deepcopy(child))

    wrapper = ET.Element("wrapper")
    for fragment in fragments:
        for expanded in expand_section_markers(fragment):
            wrapper.append(expanded)

    ET.indent(wrapper, space="  ")
    xml = ET.tostring(wrapper, encoding="unicode")
    match = re.search(r"^<wrapper>(.*)</wrapper>$", xml, re.DOTALL)
    if not match:
        return []
    inner = match.group(1).strip()
    return [block.strip() for block in re.split(r"\n\s*\n", inner) if block.strip()]


def extract_fragment_xml(converted_xml: str) -> list[str]:
    """Extract section body fragments with strict parse and recovery fallback."""
    try:
        return _extract_fragment_xml_strict(converted_xml)
    except ET.ParseError:
        recovered_xml = _recover_xml_with_lxml(converted_xml)
        if recovered_xml is None:
            raise
        return _extract_fragment_xml_strict(recovered_xml)


def separate_exercise_fragments(fragment_blocks: list[str]) -> tuple[list[str], list[str]]:
    """Split exercise nodes out of mixed fragment blocks."""
    non_exercise: list[str] = []
    exercise: list[str] = []

    def _has_exercise_descendant(node: ET.Element) -> bool:
        return any(local_name(desc.tag) == "exercise" for desc in node.iter())

    def _append_exercise_block(node: ET.Element) -> None:
        tag = local_name(node.tag)
        if tag == "exercise":
            exercise.append(ET.tostring(node, encoding="unicode").strip())
            return
        if tag == "exercisegroup":
            if _has_exercise_descendant(node):
                exercise.append(ET.tostring(node, encoding="unicode").strip())
            return
        if tag == "exercises":
            for ex_child in list(node):
                _append_exercise_block(ex_child)
            return

    def _detach_exercises(node: ET.Element) -> None:
        for child in list(node):
            tag = local_name(child.tag)
            if tag == "exercise":
                exercise.append(ET.tostring(child, encoding="unicode").strip())
                node.remove(child)
                continue
            if tag in {"exercisegroup", "exercises"}:
                _append_exercise_block(child)
                node.remove(child)
                continue
            _detach_exercises(child)

    for block in fragment_blocks:
        stripped = block.strip()
        if not stripped:
            continue
        try:
            root = ET.fromstring(stripped)
        except ET.ParseError:
            try:
                wrapper = ET.fromstring(f"<wrapper>{stripped}</wrapper>")
            except ET.ParseError:
                wrapper = None

            if wrapper is not None:
                for child in list(wrapper):
                    child_tag = local_name(child.tag)
                    if child_tag in {"exercise", "exercisegroup", "exercises"}:
                        _append_exercise_block(child)
                        continue

                    _detach_exercises(child)
                    cleaned_child = ET.tostring(child, encoding="unicode").strip()
                    if cleaned_child:
                        non_exercise.append(cleaned_child)
                continue

            extracted = re.findall(r"<exercise\b.*?</exercise>", stripped, flags=re.DOTALL)
            if extracted:
                exercise.extend(item.strip() for item in extracted)
                cleaned = re.sub(r"<exercise\b.*?</exercise>", "", stripped, flags=re.DOTALL)
                cleaned = re.sub(r"<exercisegroup\b[^>]*>.*?</exercisegroup>", "", cleaned, flags=re.DOTALL)
                cleaned = re.sub(r"<exercises\b[^>]*>.*?</exercises>", "", cleaned, flags=re.DOTALL)
                if cleaned.strip():
                    non_exercise.append(cleaned.strip())
            else:
                non_exercise.append(stripped)
            continue

        root_tag = local_name(root.tag)
        if root_tag == "exercise":
            exercise.append(stripped)
            continue
        if root_tag in {"exercisegroup", "exercises"}:
            _append_exercise_block(root)
            continue

        _detach_exercises(root)
        cleaned_root = ET.tostring(root, encoding="unicode").strip()
        if cleaned_root and cleaned_root != stripped:
            non_exercise.append(cleaned_root)
        elif cleaned_root and local_name(root.tag) not in {"exercisegroup", "exercises"}:
            non_exercise.append(cleaned_root)

    return non_exercise, exercise


def pretext_element_id(element: ET.Element) -> str:
    """Return an element ID from `xml:id`, namespaced XML id, or plain `id`."""
    return text_or_empty(
        element.attrib.get("{http://www.w3.org/XML/1998/namespace}id")
        or element.attrib.get("xml:id")
        or element.attrib.get("id")
    )


def find_pretext_element_by_id(root: ET.Element, element_id: str) -> ET.Element | None:
    wanted = text_or_empty(element_id)
    if not wanted:
        return None
    for element in root.iter():
        if pretext_element_id(element) == wanted:
            return element
    return None


def find_pretext_element_by_title(root: ET.Element, title: str) -> ET.Element | None:
    wanted = text_or_empty(title)
    if not wanted:
        return None

    lowered = wanted.casefold()
    matches: list[ET.Element] = []
    for element in root.iter():
        if local_name(element.tag) not in SECTION_TAGS:
            continue
        title_node = element.find("title")
        if title_node is None:
            continue
        candidate = text_or_empty("".join(title_node.itertext()))
        if candidate.casefold() == lowered:
            matches.append(element)

    if len(matches) == 1:
        return matches[0]
    return None


def prefix_ids_and_refs(
    fragment: ET.Element,
    prefix: str,
    *,
    resource_code: str = "SRC",
    source_path: str = "",
    target_file: str = "",
    target_section_id: str = "",
    scoped_id_registry: ScopedIdRegistry | None = None,
    license_name: str = "",
) -> ET.Element:
    scoped_prefix = slugify(prefix) or "ref"
    clean_resource = re.sub(r"[^A-Za-z0-9]+", "", (resource_code or "SRC").upper()) or "SRC"
    id_map: dict[str, str] = {}
    used_ids: set[str] = set()
    generated_counter = 0

    def _short_id(original_key: str, fallback: str) -> str:
        nonlocal generated_counter
        generated_counter += 1

        if scoped_id_registry is not None and source_path:
            scope_key = scoped_id_registry.make_simple_scope_key(
                source_path=source_path,
                resource_code=clean_resource,
                original_id=original_key,
            )
            resolved = scoped_id_registry.resolve_simple_code(
                scope_key=scope_key,
                resource_code=clean_resource,
                source_path=source_path,
                target_file=target_file,
                target_section_id=target_section_id,
                original_id=original_key,
                fallback=fallback,
                random_token_factory=_random_id_token,
            )
            used_ids.add(resolved)
            return resolved

        candidate = f"{clean_resource}-{_random_id_token(10)}"
        while candidate in used_ids:
            candidate = f"{clean_resource}-{_random_id_token(10)}"
        used_ids.add(candidate)
        return candidate

    # First pass: remap existing IDs and remember used values.

    for node in fragment.iter():
        raw_id = pretext_element_id(node)
        if not raw_id:
            continue
        mapped = id_map.get(raw_id)
        if mapped is None:
            mapped = _short_id(raw_id, "id")
            id_map[raw_id] = mapped
        used_ids.add(mapped)

        if XML_ID_ATTR in node.attrib:
            node.attrib[XML_ID_ATTR] = mapped
        elif "xml:id" in node.attrib:
            node.attrib[XML_ID_ATTR] = mapped
            del node.attrib["xml:id"]
        elif "id" in node.attrib:
            node.attrib["id"] = mapped

        if license_name and not text_or_empty(node.attrib.get("license")):
            node.attrib["license"] = license_name

    # Second pass: assign IDs to eligible nodes that still lack any ID.
    per_tag_counter: dict[str, int] = {}
    for node in fragment.iter():
        raw_id = pretext_element_id(node)
        tag = local_name(node.tag)
        if raw_id or tag not in ID_ELIGIBLE_TAGS:
            if raw_id:
                if license_name and not text_or_empty(node.attrib.get("license")):
                    node.attrib["license"] = license_name
            continue

        per_tag_counter[tag] = per_tag_counter.get(tag, 0) + 1
        synthetic_key = f"{scoped_prefix}:{tag}:{per_tag_counter[tag]}"
        node.attrib[XML_ID_ATTR] = _short_id(synthetic_key, tag)

        if license_name and not text_or_empty(node.attrib.get("license")):
            node.attrib["license"] = license_name

    for node in fragment.iter():
        for attr_name in ("ref", "first", "last", "provisional"):
            raw = text_or_empty(node.attrib.get(attr_name))
            if not raw:
                continue
            parts = [part for part in re.split(r"([\s,]+)", raw)]
            changed = False
            for i, token in enumerate(parts):
                stripped = token.strip()
                if not stripped:
                    continue
                mapped = id_map.get(stripped)
                if mapped and mapped != stripped:
                    if token == stripped:
                        parts[i] = mapped
                    else:
                        parts[i] = token.replace(stripped, mapped)
                    changed = True
            if changed:
                node.attrib[attr_name] = "".join(parts)

    return fragment


def strip_nested_include_nodes(node: ET.Element) -> None:
    """Remove nested include/webwork nodes from a fragment tree in place."""
    for child in list(node):
        child_tag = local_name(child.tag)
        if child_tag in {"include", "webwork"}:
            node.remove(child)
            continue
        strip_nested_include_nodes(child)


def remove_nodes_by_tag(fragment: ET.Element, tag_names: set[str]) -> None:
    """Remove direct child nodes whose local tag name is in `tag_names`."""
    for node in fragment.iter():
        for child in list(node):
            if local_name(child.tag) in tag_names:
                node.remove(child)


def escape_unknown_angle_tokens(xml: str) -> str:
    """Escape XML-looking tags that are not valid PreTeXt tags.
    
    Preserves LaTeX arrow syntax (e.g., <->, <-, ->) used in TikZ diagrams
    within latex-image elements.
    """
    # Pattern for valid XML-like tags: <tag_name ...>
    token_pattern = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9-]*)([^>]*)>")
    
    # Pattern for LaTeX arrow syntax: single character or hyphen operators
    latex_arrow_pattern = re.compile(r"<-?>|<-?->")

    def replacer(match: re.Match[str]) -> str:
        _slash, tag_name, _tail = match.groups()
        if tag_name in ALLOWED_XML_TAGS:
            return match.group(0)
        return match.group(0).replace("<", "&lt;").replace(">", "&gt;")

    # First, protect LaTeX arrows by replacing them with a placeholder
    arrows = []
    def save_arrow(m: re.Match[str]) -> str:
        arrows.append(m.group(0))
        return f"__LATEX_ARROW_{len(arrows) - 1}__"
    
    xml = latex_arrow_pattern.sub(save_arrow, xml)
    
    # Apply escaping to non-LaTeX angle brackets
    xml = token_pattern.sub(replacer, xml)
    
    # Restore LaTeX arrows
    for i, arrow in enumerate(arrows):
        xml = xml.replace(f"__LATEX_ARROW_{i}__", arrow)
    
    return xml
