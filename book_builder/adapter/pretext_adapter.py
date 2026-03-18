"""PreTeXt-to-PreTeXt adaptation helpers.

This module extracts scoped fragment blocks from already-PreTeXt source files
so they can be inserted into local reference sections.
"""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from pathlib import Path

from slugify import slugify

from book_builder.adapter.fragments import (
    expand_section_markers,
    find_pretext_element_by_id,
    find_pretext_element_by_title,
    prefix_ids_and_refs,
    remove_nodes_by_tag,
    section_to_paragraph_title_block,
    strip_nested_include_nodes,
)
from book_builder.adapter.models import ReferenceMatch, SECTION_TAGS, local_name, text_or_empty
from book_builder.adapter.scoped_ids import ScopedIdRegistry


def convert_pretext_reference_to_fragments(
    reference: ReferenceMatch,
    workspace_root: Path,
    target_section_id: str,
    scoped_id_registry: ScopedIdRegistry | None = None,
    target_file: Path | None = None,
) -> list[str]:
    """Convert a PreTeXt source section into scoped PTX fragments."""
    source_path = text_or_empty(reference.toc_row.get("source_path"))
    resource_slug = text_or_empty(reference.resource)
    adapted_root = workspace_root / "adapted-works"
    candidates = [
        adapted_root / source_path,
        adapted_root / resource_slug / source_path,
        adapted_root / resource_slug / "src" / source_path,
    ]
    source_file = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    if not source_file.exists():
        raise FileNotFoundError(f"PreTeXt source not found: {source_file}")

    root = ET.parse(source_file).getroot()
    selected = find_pretext_element_by_id(root, reference.ref_id)

    if selected is None:
        selected = find_pretext_element_by_title(root, reference.title)

    if selected is None:
        root_id = text_or_empty(root.attrib.get("xml:id") or root.attrib.get("id"))
        if root_id and root_id == text_or_empty(reference.ref_id):
            selected = root
        else:
            raise ValueError(f"Could not find PreTeXt id '{reference.ref_id}' in {source_file}")

    fragments: list[ET.Element] = []
    selected_tag = local_name(selected.tag)

    if selected_tag in SECTION_TAGS:
        fragments.append(section_to_paragraph_title_block(selected))

    for child in list(selected):
        child_tag = local_name(child.tag)
        if child_tag in {"title", "webwork", "include", "objectives"}:
            continue
        if child_tag == "introduction":
            for intro_child in list(child):
                intro_tag = local_name(intro_child.tag)
                if intro_tag in {"webwork", "include", "objectives"}:
                    continue
                fragments.extend(expand_section_markers(copy.deepcopy(intro_child)))
            continue
        fragments.extend(expand_section_markers(copy.deepcopy(child)))

    safe_resource = slugify(text_or_empty(reference.resource) or "src")
    safe_ref_id = slugify(text_or_empty(reference.ref_id) or "ref")
    base_prefix = f"{target_section_id}-{reference.label}-{safe_resource}-{safe_ref_id}"

    rendered: list[str] = []
    for index, fragment in enumerate(fragments, start=1):
        remove_nodes_by_tag(fragment, {"objectives"})
        strip_nested_include_nodes(fragment)
        scoped = prefix_ids_and_refs(
            fragment,
            f"{base_prefix}-{index}",
            resource_code=text_or_empty(reference.resource) or "SRC",
            source_path=source_path,
            target_file=str(target_file or ""),
            target_section_id=target_section_id,
            scoped_id_registry=scoped_id_registry,
            license_name=text_or_empty(reference.toc_row.get("License")) or "CC-BY-4.0",
        )
        xml = ET.tostring(scoped, encoding="unicode").strip()
        if xml:
            rendered.append(xml)

    return rendered
