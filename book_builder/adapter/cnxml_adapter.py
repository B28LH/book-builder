"""CNXML-to-PreTeXt adaptation bridge.

This module wraps the legacy `cnxml_to_pretext_section.py` converter and
provides a stable adapter function used by the unified population pipeline.
"""

from __future__ import annotations

import copy
import lxml.etree as ET
from pathlib import Path

from slugify import slugify

import book_builder.adapter.cnxml_to_pretext_section as cnxml
from book_builder.adapter.fragments import extract_fragment_xml, sanitize_xml_text
from book_builder.adapter.models import ReferenceMatch, local_name, text_or_empty
from book_builder.adapter.scoped_ids import ScopedIdRegistry


NS = cnxml.NS
clean_text = cnxml.clean_text


def find_element_by_id(root: ET.Element, element_id: str) -> ET.Element | None:
    """Return the first element in `root` with matching CNXML `id`."""
    for element in root.iter():
        if element.attrib.get("id") == element_id:
            return element
    return None


def build_synthetic_root(module_root: ET.Element, toc_row) -> ET.Element:
    """Create a synthetic CNXML module containing just the selected section."""
    synthetic_root = copy.deepcopy(module_root)
    content = synthetic_root.find("c:content", NS)
    if content is None:
        raise ValueError("CNXML module has no <content> element")

    for child in list(content):
        content.remove(child)

    start_level = int(toc_row["section_level"])
    row_type = text_or_empty(toc_row["row_type"])
    element_id = text_or_empty(toc_row["ID"])

    if start_level == 0 or row_type == "module":
        original_content = module_root.find("c:content", NS)
        if original_content is None:
            raise ValueError("CNXML module has no <content> element")
        new_children = [copy.deepcopy(child) for child in list(original_content)]
        selected_title = text_or_empty(toc_row["module_title"])
    else:
        selected_node = find_element_by_id(module_root, element_id)
        if selected_node is None:
            raise ValueError(f"Could not find section id '{element_id}' in module")
        selected_classes = text_or_empty(selected_node.attrib.get("class"))
        if local_name(selected_node.tag) == "section" and "section-exercises" in selected_classes.split():
            new_children = [copy.deepcopy(selected_node)]
        else:
            new_children = [copy.deepcopy(child) for child in list(selected_node) if local_name(child.tag) != "title"]
        selected_title = clean_text(selected_node.findtext("c:title", default="", namespaces=NS))
        if not selected_title:
            selected_title = text_or_empty(toc_row["section_title"])

    for child in new_children:
        content.append(child)

    title_node = synthetic_root.find("c:title", NS)
    if title_node is None:
        title_node = ET.SubElement(synthetic_root, f"{{{NS['c']}}}title")
    title_node.text = selected_title or text_or_empty(toc_row["module_title"]) or "Untitled"

    metadata_title = synthetic_root.find("c:metadata/md:title", NS)
    if metadata_title is not None:
        metadata_title.text = title_node.text

    return synthetic_root


def convert_reference_to_fragments(
    reference: ReferenceMatch,
    workspace_root: Path,
    target_file: Path,
    target_section_id: str,
    no_copy_images: bool,
    book_abbr: str,
    scoped_id_registry: ScopedIdRegistry | None = None,
) -> list[str]:
    """Convert a CNXML reference selection into PTX body fragments."""
    module_source = workspace_root / "adapted-works" / text_or_empty(reference.toc_row["source_path"])
    if not module_source.exists():
        raise FileNotFoundError(f"CNXML source not found: {module_source}")

    module_tree = ET.parse(module_source)
    module_root = module_tree.getroot()
    synthetic_root = build_synthetic_root(module_root, reference.toc_row)
    synthetic_output = target_file.with_suffix(".tmp.ptx")
    safe_abbr = slugify(text_or_empty(book_abbr) or reference.resource or "src")
    synthetic_section_id = f"{target_section_id}-{reference.label}-{safe_abbr}-{slugify(reference.ref_id)}"
    local_id_prefix = f"{safe_abbr}-{slugify(reference.ref_id)}"

    converted_xml = cnxml.build_pretext_section(
        synthetic_root,
        module_source.resolve(),
        synthetic_output.resolve(),
        workspace_root.resolve(),
        reference.resource,
        not no_copy_images,
        None,
        None,
        synthetic_section_id,
        False,
        local_id_prefix=local_id_prefix,
        randomize_scoped_ids=True,
        scoped_id_registry=scoped_id_registry,
        registry_target_file=target_file,
    )
    converted_xml = cnxml.resolve_or_downgrade_xrefs(converted_xml)
    converted_xml = cnxml.escape_ampersands_in_xml(converted_xml)
    converted_xml = cnxml.sanitize_angle_operators_outside_math(converted_xml)
    converted_xml = sanitize_xml_text(converted_xml)
    return extract_fragment_xml(converted_xml)
