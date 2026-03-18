#!/usr/bin/env python3
"""Generate PreTeXt skeleton files from the Book Structure CSV.

This script creates:
1) source/<chapter-slug>/ch-<chapter-slug>.ptx
2) source/<chapter-slug>/sec-*.ptx section templates
3) source/content.ptx with <part> entries for each strand
4) reference/* with the same generated structure as source/*

Expected CSV columns:
- Part (Strand)
- Chapter (Substrand)
- Section
- Lesson title
- Content summary
- LO 1, LO 2, LO 3, LO 4
"""

from __future__ import annotations

import argparse
import csv
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from slugify import slugify
from xml.sax.saxutils import escape


@dataclass
class SectionRow:
    title: str
    summary: str
    objectives: list[str]


def sanitize_comment(text: str) -> str:
    cleaned = " ".join(text.split())
    # XML comments cannot contain "--"
    return cleaned.replace("--", "—")


def read_rows(csv_path: Path) -> dict[str, dict[str, list[SectionRow]]]:
    """Return nested mapping: strand -> chapter -> list[SectionRow]."""
    structure: dict[str, dict[str, list[SectionRow]]] = defaultdict(lambda: defaultdict(list))

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            strand = (row.get("Part (Strand)") or "").strip()
            chapter = (row.get("Chapter (Substrand)") or "").strip()
            section = (row.get("Section") or "").strip()
            lesson_title = (row.get("Lesson title") or "").strip()

            # Skip non-content rows.
            if not strand or not chapter:
                continue

            # Most rows use "Section" as the section title. Fall back to lesson title.
            section_title = section or lesson_title
            if not section_title:
                continue

            summary = (row.get("Content summary") or "").strip()
            objectives = []
            for key in ("LO 1", "LO 2", "LO 3", "LO 4"):
                value = (row.get(key) or "").strip()
                if value:
                    objectives.append(value)

            structure[strand][chapter].append(
                SectionRow(title=section_title, summary=summary, objectives=objectives)
            )

    return structure


def unique_section_filename(base_slug: str, seen: dict[str, int]) -> str:
    idx = seen.get(base_slug, 0)
    seen[base_slug] = idx + 1
    if idx == 0:
        return f"sec-{base_slug}.ptx"
    return f"sec-{base_slug}-{idx + 1}.ptx"


def render_section_file(section_id: str, section_title: str, summary: str, objectives: list[str]) -> str:
    title_xml = escape(section_title)
    summary_comment = sanitize_comment(summary) if summary else ""

    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "",
        f'<section xml:id="{section_id}">',
        f"  <title>{title_xml}</title>",
        "",
    ]

    if summary_comment:
        lines.append(f"  <!-- Content summary: {summary_comment} -->")
        lines.append("")

    lines.extend(
        [
            "  <objectives>",
            "    <ul>",
        ]
    )

    if objectives:
        for lo in objectives:
            lines.append(f"      <li>{escape(lo)}</li>")
    else:
        lines.append("      <li>TODO: add learning objective.</li>")

    lines.extend(
        [
            "    </ul>",
            "  </objectives>",
            "",
            "  <!-- Add <insight> here -->"
            "  <!-- TODO: add section content. -->",
            "</section>",
            "",
        ]
    )

    return "\n".join(lines)


def render_chapter_file(chapter_id: str, chapter_title: str, section_files: list[str]) -> str:
    title_xml = escape(chapter_title)
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "",
        f'<chapter xml:id="{chapter_id}" xmlns:xi="http://www.w3.org/2001/XInclude">',
        f"  <title>{title_xml}</title>",
        "",
        "  <introduction>",
        "    <!-- TODO: Add introduction -->",
        "  </introduction>",
        "",
        "  <!-- include sections -->",
        "  <!-- <xi:include href=\"sec-section-name.ptx\" /> -->",
    ]

    for sec in section_files:
        lines.append(f'  <xi:include href="{sec}" />')

    lines.extend(["", "</chapter>", ""])
    return "\n".join(lines)


def build_chapter_folder_map(structure: dict[str, dict[str, list[SectionRow]]]) -> dict[tuple[str, str], str]:
    chapter_folders: dict[tuple[str, str], str] = {}
    chapter_number = 1

    for strand, chapters in structure.items():
        for chapter in chapters:
            chapter_slug = slugify(chapter)
            chapter_folders[(strand, chapter)] = f"{chapter_number:02d}-{chapter_slug}"
            chapter_number += 1

    return chapter_folders


def render_content_file(
    structure: dict[str, dict[str, list[SectionRow]]],
    chapter_folders: dict[tuple[str, str], str],
) -> str:
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        "",
        '<pretext xml:lang="en-US" xmlns:xi="http://www.w3.org/2001/XInclude">',
        '  <book xml:id="generated-content">',
    ]

    for strand, chapters in structure.items():
        part_id = f"part-{slugify(strand)}"
        lines.extend(
            [
                f'  <part xml:id="{part_id}">',
                f"    <title>{escape(strand)}</title>",
                "",
            ]
        )

        for chapter in chapters:
            chapter_slug = slugify(chapter)
            chapter_folder = chapter_folders[(strand, chapter)]
            lines.append(f'    <xi:include href="./{chapter_folder}/ch-{chapter_slug}.ptx" />')

        lines.extend(["", "  </part>", ""])

    lines.extend(["  </book>", "</pretext>", ""])
    return "\n".join(lines)


def generate(structure: dict[str, dict[str, list[SectionRow]]], source_dir: Path) -> None:
    chapter_folders = build_chapter_folder_map(structure)

    for strand, chapters in structure.items():
        for chapter_title, sections in chapters.items():
            chapter_slug = slugify(chapter_title)
            chapter_folder = chapter_folders[(strand, chapter_title)]
            chapter_dir = source_dir / chapter_folder

            legacy_chapter_dir = source_dir / chapter_slug
            if legacy_chapter_dir.exists() and not chapter_dir.exists():
                legacy_chapter_dir.rename(chapter_dir)

            chapter_dir.mkdir(parents=True, exist_ok=True)

            seen_section_slugs: dict[str, int] = {}
            chapter_section_files: list[str] = []

            for sec in sections:
                section_slug = slugify(sec.title)
                section_filename = unique_section_filename(section_slug, seen_section_slugs)
                section_id = section_filename.removesuffix(".ptx")
                section_path = chapter_dir / section_filename

                section_path.write_text(
                    render_section_file(section_id, sec.title, sec.summary, sec.objectives),
                    encoding="utf-8",
                )
                chapter_section_files.append(section_filename)

            chapter_file = chapter_dir / f"ch-{chapter_slug}.ptx"
            chapter_id = chapter_file.stem
            chapter_file.write_text(
                render_chapter_file(chapter_id, chapter_title, chapter_section_files),
                encoding="utf-8",
            )

    content_file = source_dir / "content.ptx"
    content_file.write_text(render_content_file(structure, chapter_folders), encoding="utf-8")


def copy_supporting_book_files(from_dir: Path, to_dir: Path) -> None:
    """Copy shared book-level files (frontmatter/docinfo/backmatter) from one tree to another."""
    for name in ("frontmatter.ptx", "docinfo.ptx", "backmatter.ptx"):
        src = from_dir / name
        dst = to_dir / name
        if src.exists():
            shutil.copy2(src, dst)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate empty PreTeXt structure files from Book Structure CSV")
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path("textbook_info/Book Structure.csv"),
        help="Path to the Book Structure CSV",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("source"),
        help="Path to the PreTeXt source directory",
    )
    parser.add_argument(
        "--reference",
        type=Path,
        default=Path("reference"),
        help="Path to the generated reference directory",
    )
    args = parser.parse_args()

    csv_path = args.csv.resolve()
    source_dir = args.source.resolve()
    reference_dir = args.reference.resolve()

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    if not source_dir.exists():
        source_dir.mkdir(parents=True, exist_ok=True)
        # raise FileNotFoundError(f"Source directory not found: {source_dir}")
    reference_dir.mkdir(parents=True, exist_ok=True)

    structure = read_rows(csv_path)
    if not structure:
        raise ValueError("No valid strand/chapter/section rows were found in the CSV")

    generate(structure, source_dir)
    generate(structure, reference_dir)
    copy_supporting_book_files(source_dir, reference_dir)

    chapter_count = sum(len(chapters) for chapters in structure.values())
    section_count = sum(len(sections) for chapters in structure.values() for sections in chapters.values())
    print(f"Generated {chapter_count} chapter folders and {section_count} section files in {source_dir}")
    print(f"Wrote content include file: {source_dir / 'content.ptx'}")
    print(f"Generated {chapter_count} chapter folders and {section_count} section files in {reference_dir}")
    print(f"Wrote content include file: {reference_dir / 'content.ptx'}")


if __name__ == "__main__":
    main()
