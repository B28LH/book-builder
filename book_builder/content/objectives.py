"""Support routines for inserting "objectives" blocks into PTX text.

This should not be needed if `create_book_skeleton.py' is used to create the skeleton

The module does *not* read or write files.
Higher-level code can call `insert_objectives` repeatedly over rows from the
links CSV.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from typing import List, Dict

from book_builder.helpers._text import detect_newline, indent_of_line
import pandas as pd
from book_builder.helpers import _csvtools


# path to the automatic links CSV; use cached location
AUTOMATIC_LINKS_PATH = _csvtools.cached_file("Automatic Links.csv")


# -------------------------------------------------------------
# numbering helpers copied from the original helper script
# -------------------------------------------------------------

def build_numbering(df: pd.DataFrame) -> Dict[str, Dict]:
    """Return chapter/section numbering maps from an Automatic Links DataFrame.

    The returned dictionary has two keys, ``chapter_num`` and ``section_num``.
    ``chapter_num`` maps chapter names to strings like ``"1.0"``.
    ``section_num`` maps ``(chapter, section)`` tuples to strings like
    ``"1.2"``.
    """
    chapters = df["Chapter"].dropna().unique().tolist()
    chapter_num: Dict[str, str] = {}
    for i, ch in enumerate(chapters, start=1):
        chapter_num[ch] = f"{i}.0"

    section_num: Dict[tuple[str, str], str] = {}
    for ch in chapters:
        ch_df = df[df["Chapter"] == ch]
        sections = ch_df["Section"].dropna().unique().tolist()
        ch_idx = int(chapter_num[ch].split(".")[0])
        for j, sec in enumerate(sections, start=1):
            section_num[(ch, sec)] = f"{ch_idx}.{j}"

    return {"chapter_num": chapter_num, "section_num": section_num}


# -------------------------------------------------------------
# block creation and insertion functions
# -------------------------------------------------------------

def build_objectives_block(
    indent: str,
    chapter: str,
    section: str,
    chapter_num: str,
    section_num: str,
    learning_outcomes: List[str],
    newline: str,
) -> str:
    """Return an objectives XML fragment indented to match *indent*.

    The caller is responsible for determining *indent* (typically by
    examining the title line) and for writing the returned string back into
    the document.
    """
    inner = indent + "    "
    inner2 = inner + "    "
    inner3 = inner2 + "    "

    # build list items
    lo_items = ""
    for lo in learning_outcomes:
        lo_items += f"{inner2}<li>{lo}</li>{newline}"
    lo_items = lo_items.rstrip(newline)

    block = f"""{indent}<objectives component="outcomes">
{inner}<introduction>
{inner2}<dl>
{inner3}<li>
{inner3}    <title>Strand</title>
{inner3}    <p>
{inner3}        {chapter_num} {chapter}
{inner3}    </p>
{inner3}</li>
{inner3}<li>
{inner3}    <title>Sub-Strand</title>
{inner3}    <p>
{inner3}        {section_num} {section}
{inner3}    </p>
{inner3}</li>
{inner2}</dl>
{inner}</introduction>
{inner}<ul>
{lo_items}
{inner}</ul>
{indent}</objectives>"""
    return block.replace("\n", newline)


def has_objectives(content: str) -> bool:
    """Return True if *content* already contains an objectives block."""
    return '<objectives component="outcomes">' in content


def insert_objectives(
    content: str,
    chapter: str,
    section: str,
    chapter_num: str,
    section_num: str,
    learning_outcomes: List[str],
) -> str | None:
    """Return text with an objectives block inserted, or ``None`` if no
    insertion was needed.

    The rules mirror the original script:

    * do nothing if the file already has an objectives block;
    * find the first ``</title>`` tag and insert immediately after it.
    """
    if has_objectives(content):
        return None

    title_index = content.find("</title>")
    if title_index == -1:
        return None

    newline = detect_newline(content)
    title_line_start = content.rfind(newline, 0, title_index)
    if title_line_start == -1:
        title_line_start = 0
    else:
        title_line_start += len(newline)
    title_line_end = content.find(newline, title_index)
    if title_line_end == -1:
        title_line_end = len(content)
    title_line = content[title_line_start:title_line_end]
    indent = title_line[: len(title_line) - len(title_line.lstrip())]

    block = build_objectives_block(
        indent,
        chapter,
        section,
        chapter_num,
        section_num,
        learning_outcomes,
        newline,
    )

    insert_pos = title_index + len("</title>")
    return content[:insert_pos] + newline + block + content[insert_pos:]


def cmd_add_objectives(*, links_csv_path: Path | None = None, source_dir: Path | str = Path("source")) -> None:
    """Insert objectives blocks into PTX files listed in the links CSV."""
    csv_path = links_csv_path or AUTOMATIC_LINKS_PATH
    source_root = Path(source_dir)

    df = pd.read_csv(csv_path, encoding="utf-8", na_filter=False)
    numbering = build_numbering(df)
    chap_map = numbering["chapter_num"]
    sec_map = numbering["section_num"]

    added = 0
    skipped = 0

    for row in df.to_dict(orient="records"):
        if row.get("PTX Exists") != "YES":
            continue

        ptx_rel = row.get("PTX Path", "").strip()
        chapter = (row.get("Chapter") or "").strip()
        section = (row.get("Section") or "").strip()
        if not chapter or not section or not ptx_rel:
            continue

        los = [row.get(f"LO {i}", "").strip() for i in range(1, 5) if row.get(f"LO {i}")]
        los = [lo for lo in los if lo]
        if not los:
            continue

        ch_num = chap_map.get(chapter, "?.0")
        sec_num = sec_map.get((chapter, section), "?.?")
        path = source_root / ptx_rel
        text = path.read_text(encoding="utf-8")

        new = insert_objectives(text, chapter, section, ch_num, sec_num, los)
        if new is not None:
            path.write_text(new, encoding="utf-8")
            added += 1
        else:
            skipped += 1

    print(f"objectives added: {added}, skipped-existing: {skipped}")
    print("add-objectives: done")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Insert objectives blocks into PTX files")
    parser.add_argument(
        "--links-csv",
        type=Path,
        default=AUTOMATIC_LINKS_PATH,
        help="Path to Automatic Links CSV (default: textbook_info/Automatic Links.csv)",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("source"),
        help="Root source directory for PTX paths (default: source)",
    )
    args = parser.parse_args(argv)
    cmd_add_objectives(links_csv_path=args.links_csv, source_dir=args.source_dir)


if __name__ == "__main__":
    main()
