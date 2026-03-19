#!/usr/bin/env python3
"""Export a PreTeXt table of contents to CSV by resolving ``xi:include`` files.

The script starts from any PreTeXt XML/PTX file, follows included files in
document order, and writes one CSV row per structural node. The output schema
expands dynamically to include one set of columns per depth level, making it
reusable across books with different nesting depths.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import random
import string
import lxml.etree as ET


XI_NAMESPACE = "http://www.w3.org/2001/XInclude"
STRUCTURAL_TAGS = {
    "article",
    "appendix",
    "acknowledgement",
    "backmatter",
    "biography",
    "book",
    "chapter",
    "conclusion",
    "exercises",
    "foreword",
    "frontmatter",
    "glossary",
    "index",
    "introduction",
    "paragraphs",
    "part",
    "preface",
    "references",
    "section",
    "solutions",
    "subsection",
    "subsubsection",
}
TITLE_FALLBACKS = {
    "acknowledgement": "Acknowledgement",
    "backmatter": "Backmatter",
    "frontmatter": "Frontmatter",
    "glossary": "Glossary",
    "index": "Index",
    "introduction": "Introduction",
    "references": "References",
    "solutions": "Solutions",
}

# Characters used when generating a fallback node ID (0-9, a-z, A-Z).
_ID_CHARS = string.digits + string.ascii_lowercase + string.ascii_uppercase


def generate_node_id(resource_name: str, length: int = 10) -> str:
    """Generate a new node ID: *resource_name* followed by *length* random alphanumeric chars."""
    suffix = "".join(random.choices(_ID_CHARS, k=length))
    return f"{resource_name}{suffix}"


@dataclass(frozen=True)
class TocNode:
    """A single structural node in the resolved PreTeXt hierarchy."""

    tag: str
    original_id: str
    node_id: str
    title: str
    source_path: str


@dataclass(frozen=True)
class TocRow:
    """One CSV row, including the node and its full ancestry."""

    order: int
    node: TocNode
    lineage: tuple[TocNode, ...]


def local_name(tag: object) -> str:
    """Return an XML tag name without its namespace prefix."""

    if not isinstance(tag, str):
        return ""

    if tag.startswith("{"):
        return tag.rsplit("}", 1)[1]
    return tag


def normalize_text(text: str) -> str:
    """Collapse internal whitespace so titles are CSV-friendly."""

    return " ".join(text.split())


def normalize_element_text(element: ET.Element | None) -> str:
    """Extract and normalize all descendant text from an element."""

    if element is None:
        return ""
    return normalize_text("".join(element.itertext()))


def sanitize_unmatched_comment_closers(xml_text: str) -> str:
    """Remove orphaned ``-->`` tokens that appear outside an XML comment.

    Some borrowed sources contain lines such as ``<xi:include ... /> -->``.
    Those are not well-formed XML, but we can recover safely by dropping only
    the unmatched comment closers while preserving valid block comments.
    """

    cleaned_lines: list[str] = []
    comment_depth = 0

    for line in xml_text.splitlines(keepends=True):
        open_count = line.count("<!--")
        close_count = line.count("-->")
        unmatched_closers = max(0, close_count - open_count - comment_depth)

        if unmatched_closers:
            for _ in range(unmatched_closers):
                line = line.replace("-->", "", 1)
            close_count -= unmatched_closers

        cleaned_lines.append(line)
        comment_depth = max(0, comment_depth + open_count - close_count)

    return "".join(cleaned_lines)


def parse_xml(xml_file: Path) -> ET.Element:
    """Parse XML, retrying once with a small sanitization step if needed."""

    xml_bytes = xml_file.read_bytes()

    try:
        return ET.fromstring(xml_bytes)
    except ET.ParseError:
        # Some borrowed sources are almost valid XML apart from stray comment
        # closers, so try a minimal repair before failing hard.
        xml_text = xml_bytes.decode("utf-8", errors="replace")
        sanitized = sanitize_unmatched_comment_closers(xml_text)
        try:
            return ET.fromstring(sanitized.encode("utf-8"))
        except ET.ParseError as exc:
            raise ValueError(f"Could not parse XML file: {xml_file}") from exc


def direct_child(element: ET.Element, tag_name: str) -> ET.Element | None:
    """Return the first direct child matching a local tag name."""

    for child in element:
        if local_name(child.tag) == tag_name:
            return child
    return None


def extract_title(element: ET.Element) -> str:
    """Read a node title, falling back to a tag-based label when helpful."""

    title = normalize_element_text(direct_child(element, "title"))
    if title:
        return title

    tag_name = local_name(element.tag)
    return TITLE_FALLBACKS.get(tag_name, "")


def extract_node_id(element: ET.Element) -> str:
    """Return either `xml:id` or plain `id`, whichever is present."""

    return (
        element.get("{http://www.w3.org/XML/1998/namespace}id")
        or element.get("id")
        or ""
    )


def to_relative_path(path: Path, relative_to: Path) -> str:
    """Format a path relative to the requested base when possible."""

    try:
        return path.relative_to(relative_to).as_posix()
    except ValueError:
        return path.as_posix()


def is_include(element: ET.Element) -> bool:
    """Return whether the element is an XInclude directive."""

    return element.tag == f"{{{XI_NAMESPACE}}}include"


def include_should_be_followed(element: ET.Element) -> bool:
    """Follow only XML includes, not `parse="text"` assets like `.pg` files."""

    parse_mode = (element.get("parse") or "xml").strip().lower()
    return parse_mode in {"", "xml"}


def is_structural(element: ET.Element) -> bool:
    """Return whether the element should appear as a TOC node."""

    return local_name(element.tag) in STRUCTURAL_TAGS


def build_node(element: ET.Element, source_file: Path, relative_to: Path, resource_name: str) -> TocNode:
    """Convert an XML element into a normalized TOC node.

    Every node receives a freshly generated ID of the form
    ``{resource_name}{10 random alphanumeric chars}``.  The original
    ``xml:id`` / ``id`` attribute value (if any) is preserved in
    ``original_id`` so a mapping can be built between old and new identifiers.
    """

    return TocNode(
        tag=local_name(element.tag),
        original_id=extract_node_id(element),
        node_id=generate_node_id(resource_name),
        title=extract_title(element),
        source_path=to_relative_path(source_file, relative_to),
    )


def walk_document(
    element: ET.Element,
    *,
    source_file: Path,
    relative_to: Path,
    ancestors: tuple[TocNode, ...],
    active_files: tuple[Path, ...],
    resource_name: str,
    rows: list[TocRow],
) -> None:
    """Traverse a document tree and append TOC rows in document order."""

    current_ancestors = ancestors

    if is_structural(element):
        current_node = build_node(element, source_file, relative_to, resource_name)
        # Each structural node extends the lineage that will be attached to
        # descendants and emitted into the flattened `level_*` CSV columns.
        current_ancestors = ancestors + (current_node,)
        rows.append(TocRow(order=len(rows) + 1, node=current_node, lineage=current_ancestors))

    for child in element:
        if is_include(child):
            if not include_should_be_followed(child):
                continue

            href = (child.get("href") or "").strip()
            if not href:
                continue

            include_path = (source_file.parent / href).resolve()
            if include_path in active_files:
                cycle = " -> ".join(path.name for path in active_files + (include_path,))
                raise ValueError(f"Detected cyclic xi:include chain: {cycle}")
            if not include_path.exists():
                raise FileNotFoundError(f"Included file not found: {include_path}")

            included_root = parse_xml(include_path)
            # Switch `source_file` so rows reflect the file that actually defines
            # the included content, while preserving the current ancestor chain.
            walk_document(
                included_root,
                source_file=include_path,
                relative_to=relative_to,
                ancestors=current_ancestors,
                active_files=active_files + (include_path,),
                resource_name=resource_name,
                rows=rows,
            )
            continue

        walk_document(
            child,
            source_file=source_file,
            relative_to=relative_to,
            ancestors=current_ancestors,
            active_files=active_files,
            resource_name=resource_name,
            rows=rows,
        )


def export_toc(
    root_file: Path,
    output_file: Path,
    relative_to: Path,
    resource_name: str,
    mapping_file: Path | None = None,
) -> int:
    """Resolve a PreTeXt root file and write the resulting TOC CSV.

    Alongside the main TOC a mapping CSV is written (next to *output_file* by
    default, or at *mapping_file* when supplied) that records the original
    ``xml:id`` / ``id`` value and the freshly generated identifier for every
    structural node.
    """

    root_path = root_file.resolve()
    root_element = parse_xml(root_path)

    rows: list[TocRow] = []
    walk_document(
        root_element,
        source_file=root_path,
        relative_to=relative_to.resolve(),
        ancestors=(),
        active_files=(root_path,),
        resource_name=resource_name,
        rows=rows,
    )

    max_depth = max((len(row.lineage) for row in rows), default=0)
    # The CSV expands to the deepest lineage encountered so it works across
    # books with different structural depth.
    fieldnames = [
        "document_order",
        "depth",
        "node_type",
        "node_id",
        "original_id",
        "node_title",
        "source_path",
    ]
    for depth in range(1, max_depth + 1):
        fieldnames.extend(
            [
                f"level_{depth}_type",
                f"level_{depth}_id",
                f"level_{depth}_title",
            ]
        )

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            record = {
                "document_order": row.order,
                "depth": len(row.lineage),
                "node_type": row.node.tag,
                "node_id": row.node.node_id,
                "original_id": row.node.original_id,
                "node_title": row.node.title,
                "source_path": row.node.source_path,
            }
            for index in range(max_depth):
                prefix = f"level_{index + 1}"
                if index < len(row.lineage):
                    node = row.lineage[index]
                    record[f"{prefix}_type"] = node.tag
                    record[f"{prefix}_id"] = node.node_id
                    record[f"{prefix}_title"] = node.title
                else:
                    record[f"{prefix}_type"] = ""
                    record[f"{prefix}_id"] = ""
                    record[f"{prefix}_title"] = ""

            writer.writerow(record)

    # Write the ID mapping file.
    resolved_mapping = mapping_file or default_mapping_path(output_file)
    resolved_mapping.parent.mkdir(parents=True, exist_ok=True)
    mapping_fieldnames = ["original_id", "new_id", "node_type", "node_title", "source_path"]
    with resolved_mapping.open("w", encoding="utf-8", newline="") as map_file:
        map_writer = csv.DictWriter(map_file, fieldnames=mapping_fieldnames)
        map_writer.writeheader()
        for row in rows:
            map_writer.writerow(
                {
                    "original_id": row.node.original_id,
                    "new_id": row.node.node_id,
                    "node_type": row.node.tag,
                    "node_title": row.node.title,
                    "source_path": row.node.source_path,
                }
            )

    print(f"Wrote {len(rows)} ID mappings to {resolved_mapping}")
    return len(rows)


def default_mapping_path(toc_file: Path) -> Path:
    """Return the default ID-mapping CSV path next to *toc_file*.

    A trailing ``-toc`` suffix is stripped so ``main-toc.csv`` becomes
    ``main-id-mapping.csv`` rather than ``main-toc-id-mapping.csv``.
    """

    stem = toc_file.stem
    if stem.endswith("-toc"):
        stem = stem[: -len("-toc")]
    return toc_file.with_name(f"{stem}-id-mapping.csv")


def run_pretext_toc(
    root: Path,
    output_name: Path | None = None,
    relative_to: Path | None = None,
    resource_name: str | None = None,
    mapping_output: Path | None = None,
) -> int:
    if not output_name:
        output_name = Path(f"{root.stem}-toc.csv")

    output_folder = Path(".") / "reference_tocs"
    output_folder.mkdir(parents=True, exist_ok=True)

    output_file = output_folder / output_name
    root_file = root.resolve()
    if not root_file.exists():
        raise FileNotFoundError(f"Root file not found: {root_file}")

    relative_to = relative_to.resolve() if relative_to else root_file.parent
    effective_resource_name = resource_name if resource_name else root_file.stem.upper()
    mapping_file = mapping_output.resolve() if mapping_output else None

    row_count = export_toc(
        root_file=root_file,
        output_file=output_file,
        relative_to=relative_to,
        resource_name=effective_resource_name,
        mapping_file=mapping_file,
    )
    return row_count