#!/usr/bin/env python3
"""Export a collxml collection's table of contents to CSV.

The script walks a collection file in document order, resolves each referenced
module in the sibling ``modules/`` directory, records the module title, and
also records the title of every titled ``<section>`` element found inside that
module's CNXML.
"""

from __future__ import annotations

import argparse
import csv
import lxml.etree as ET
from pathlib import Path

NS = {
    "c": "http://cnx.rice.edu/cnxml",
    "col": "http://cnx.rice.edu/collxml",
    "md": "http://cnx.rice.edu/mdml",
}

CNXML_NS = NS["c"]


def qname(namespace: str, tag: str) -> str:
    return f"{{{namespace}}}{tag}"


def normalized_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def collection_basename(collection_file: Path) -> str:
    suffix = ".collection.xml"
    if collection_file.name.endswith(suffix):
        return collection_file.name[: -len(suffix)]
    return collection_file.stem


def read_collection_title(collection_file: Path) -> str:
    tree = ET.parse(collection_file)
    root = tree.getroot()
    return root.findtext("md:title", default="", namespaces=NS).strip() or collection_basename(collection_file)


def read_module_title(module_file: Path) -> str:
    tree = ET.parse(module_file)
    root = tree.getroot()

    title = root.findtext("c:metadata/md:title", default="", namespaces=NS).strip()
    if not title:
        title = root.findtext("c:title", default="", namespaces=NS).strip()
    return title or module_file.parent.name


def extract_section_rows(module_file: Path) -> list[dict[str, str | int]]:
    tree = ET.parse(module_file)
    root = tree.getroot()
    content = root.find("c:content", NS)
    if content is None:
        return []

    rows: list[dict[str, str | int]] = []

    def walk(node: ET.Element, level: int) -> None:
        for child in node:
            if child.tag == qname(CNXML_NS, "section"):
                title = normalized_text(child.find("c:title", NS))
                if title:
                    rows.append(
                        {
                            "section_order": len(rows) + 1,
                            "section_level": level + 1,
                            "section_id": child.get("id", ""),
                            "section_title": title,
                        }
                    )
                walk(child, level + 1)
            else:
                walk(child, level)

    walk(content, 0)
    return rows


def walk_collection_rows(
    node: ET.Element,
    *,
    collection_title: str,
    modules_root: Path,
    chapter_order: int,
    chapter_title: str,
    chapter_path: tuple[str, ...],
) -> tuple[list[dict[str, str | int]], int]:
    rows: list[dict[str, str | int]] = []
    module_order = 0

    for child in node:
        if child.tag == qname(NS["col"], "module"):
            module_id = (child.get("document") or "").strip()
            if not module_id:
                continue

            module_order += 1
            module_file = modules_root / module_id / "index.cnxml"
            if not module_file.exists():
                raise FileNotFoundError(f"Module CNXML not found: {module_file}")

            module_title = read_module_title(module_file)
            relative_module = module_file.relative_to(modules_root.parent.parent).as_posix()

            base_row = {
                "collection_title": collection_title,
                "chapter_order": chapter_order if chapter_path else "",
                "chapter_title": chapter_title,
                "subcollection_path": " > ".join(chapter_path),
                "module_order": module_order,
                "module_id": module_id,
                "module_title": module_title,
                "source_path": relative_module,
            }

            rows.append(
                {
                    **base_row,
                    "row_type": "module",
                    "section_order": "",
                    "section_level": "",
                    "section_id": "",
                    "section_title": "",
                }
            )

            for section in extract_section_rows(module_file):
                rows.append(
                    {
                        **base_row,
                        "row_type": "section",
                        **section,
                    }
                )

        elif child.tag == qname(NS["col"], "subcollection"):
            title = normalized_text(child.find("md:title", NS)) or "Untitled"
            content = child.find("col:content", NS)
            if content is None:
                continue

            next_path = chapter_path + (title,)
            next_chapter_order = chapter_order
            next_chapter_title = chapter_title
            if not chapter_path:
                next_chapter_order += 1
                next_chapter_title = title

            nested_rows, nested_chapter_order = walk_collection_rows(
                content,
                collection_title=collection_title,
                modules_root=modules_root,
                chapter_order=next_chapter_order,
                chapter_title=next_chapter_title,
                chapter_path=next_path,
            )
            rows.extend(nested_rows)
            chapter_order = nested_chapter_order

    return rows, chapter_order


def export_toc(collection_file: Path, modules_root: Path, output_file: Path) -> None:
    tree = ET.parse(collection_file)
    root = tree.getroot()
    content = root.find("col:content", NS)
    if content is None:
        raise ValueError(f"Collection has no content: {collection_file}")

    collection_title = read_collection_title(collection_file)
    rows, _ = walk_collection_rows(
        content,
        collection_title=collection_title,
        modules_root=modules_root,
        chapter_order=0,
        chapter_title="",
        chapter_path=(),
    )

    output_file.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "collection_title",
        "chapter_order",
        "chapter_title",
        "subcollection_path",
        "module_order",
        "module_id",
        "module_title",
        "row_type",
        "section_order",
        "section_level",
        "section_id",
        "section_title",
        "source_path"
    ]

    with output_file.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_stax_toc(
    resource_folder: Path,
    collection_name: str,
    output_name: Path | None = None
) -> Path:
    collection_file = resource_folder / "collections" / f"{collection_name}.collection.xml"
    if not collection_file.exists():
        raise FileNotFoundError(f"Collection file not found: {collection_file}")
    
    modules_root = resource_folder / "modules"

    if not output_name:
        output_name = Path(f"{collection_basename(collection_file)}-toc.csv")

    output_folder = Path(".") / "reference_tocs"
    if not output_folder.exists():
        print(f"Creating output folder: {output_folder}")
        output_folder.mkdir(parents=True, exist_ok=True)
        
    output_file = output_folder / output_name

    export_toc(collection_file, modules_root, output_file)
    return output_file