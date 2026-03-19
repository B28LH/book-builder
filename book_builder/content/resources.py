"""Utilities for managing lesson‑plan resource boxes in PTX text.

The functions here encapsulate the mutation logic that was previously buried in
`helpers/add_resource_boxes.py`.  They are all pure text transformations and can
be unit‑tested independently.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from book_builder.helpers._text import detect_newline
from book_builder.helpers import _csvtools


# path to the automatic links CSV; use cached location
AUTOMATIC_LINKS_PATH = _csvtools.cached_file("Automatic Links.csv")


# ------------------------------------------------------------------
# builder
# ------------------------------------------------------------------

def build_axiom(indent: str, lesson_plan: str, step_by_step: Optional[str], newline: str) -> str:
    """Return a new-style axiom block for the given URLs.

    * If *step_by_step* is ``None`` only a single ``Lesson Plan`` link is
      produced.
    * *indent* is the whitespace that should appear at the start of each new
      line (typically taken from the line containing ``</objectives>``).
    """
    inner = indent + "    "
    inner2 = inner + "    "
    inner3 = inner2 + "    "
    inner4 = inner3 + "    "

    if step_by_step is None:
        block = f"""
{indent}<axiom component=\"resources\">
{inner}<!-- Link to blurb -->
{inner}<xi:include href=\"../../resources-blurb-lesson.ptx\" />

{inner}<p>
{inner2}<dataurl source=\"{lesson_plan}\"> Lesson Plan </dataurl>
{inner}</p>
{indent}</axiom>
"""
    else:
        block = f"""
{indent}<axiom component=\"resources\">
{inner}<!-- Link to blurb -->
{inner}<xi:include href=\"../../resources-blurb-lesson.ptx\" />

{inner}<sbsgroup widths=\"45% 45%\" margins=\"2% 2%\">
{inner2}<sidebyside>
{inner3}<p>
{inner4}<dataurl source=\"{lesson_plan}\"> Lesson Plan </dataurl>
{inner3}</p>
{inner3}<p>
{inner4}<dataurl source=\"{step_by_step}\"> Step-by-Step Guide </dataurl>
{inner3}</p>
{inner2}</sidebyside>
{inner}</sbsgroup>
{indent}</axiom>
"""
    block = block.strip("\n")
    return f"{newline}{block}{newline}{newline}"


# ------------------------------------------------------------------
# insertion / upgrade logic
# ------------------------------------------------------------------

def insert_axiom_if_missing(content: str, lesson_plan: str, step_by_step: Optional[str]) -> Optional[str]:
    """Insert a resource box unless one already exists (checked via blurb URL)."""
    if "../../resources-blurb-lesson.ptx" in content:
        return None

    objectives_index = content.find("</objectives>")
    if objectives_index == -1:
        return None

    newline = detect_newline(content)
    line_start = content.rfind(newline, 0, objectives_index)
    if line_start == -1:
        line_start = 0
    else:
        line_start += len(newline)
    line_end = content.find(newline, objectives_index)
    if line_end == -1:
        line_end = len(content)
    line = content[line_start:line_end]
    indent = line[: len(line) - len(line.lstrip())]

    block = build_axiom(indent, lesson_plan, step_by_step, newline)
    insert_pos = objectives_index + len("</objectives>")
    return content[:insert_pos] + block + content[insert_pos:]


def remove_old_resource_boxes(content: str) -> Tuple[str, int]:
    """Drop any legacy <axiom> blocks that mention "offline lesson plan".

    Returns a tuple of (updated_content, number_removed).
    """
    phrase = "offline lesson plan"
    lowered = content.lower()
    removed = 0
    pieces: list[str] = []
    i = 0
    n = len(content)

    while True:
        start = content.find("<axiom", i)
        if start == -1:
            pieces.append(content[i:])
            break
        pieces.append(content[i:start])
        end = content.find("</axiom>", start)
        if end == -1:
            pieces.append(content[start:])
            break
        end_close = end + len("</axiom>")
        block = content[start:end_close]
        block_lower = lowered[start:end_close]
        if phrase in block_lower:
            removed += 1
            j = end_close
            while j < n and content[j] in " \t\r\n":
                j += 1
            i = j
        else:
            pieces.append(block)
            i = end_close
    return "".join(pieces), removed


def upgrade_lesson_only_resource_boxes(
    content: str, lesson_plan: str, step_by_step: Optional[str]
) -> Tuple[str, int]:
    """If a side-by-side guide now exists, replace old lesson-only boxes.

    Returns (updated_content, number_upgraded).
    """
    if step_by_step is None or "../../resources-blurb-lesson.ptx" not in content:
        return content, 0

    newline = detect_newline(content)
    lowered = content.lower()
    upgraded = 0
    pieces: list[str] = []
    i = 0
    n = len(content)

    while True:
        start = content.find("<axiom", i)
        if start == -1:
            pieces.append(content[i:])
            break
        pieces.append(content[i:start])
        end = content.find("</axiom>", start)
        if end == -1:
            pieces.append(content[start:])
            break
        end_close = end + len("</axiom>")
        block = content[start:end_close]
        block_lower = lowered[start:end_close]
        if (
            "../../resources-blurb-lesson.ptx" in block_lower
            and "lesson plan" in block_lower
            and "step-by-step guide" not in block_lower
        ):
            line_start = content.rfind(newline, 0, start)
            if line_start == -1:
                line_start = 0
            else:
                line_start += len(newline)
            line = content[line_start:start]
            indent = line[: len(line) - len(line.lstrip())]
            new_block = build_axiom(indent, lesson_plan, step_by_step, newline).strip("\r\n")
            pieces.append(new_block)
            upgraded += 1
            i = end_close
        else:
            pieces.append(block)
            i = end_close
    return "".join(pieces), upgraded


def cmd_add_resources(*, links_csv_path: Path | None = None, source_dir: Path | str = Path("source")) -> None:
    """Insert or upgrade lesson-plan resource boxes in PTX files."""
    print("add-resources: starting")
    csv_path = links_csv_path or AUTOMATIC_LINKS_PATH
    source_root = Path(source_dir)

    df = pd.read_csv(csv_path, encoding="utf-8")
    added = 0
    removed = 0
    upgraded = 0
    onlylesson = 0

    for row in df.to_dict(orient="records"):
        if row.get("PTX Exists") != "YES" or row.get("Lesson Plan Exists") != "YES":
            continue

        ptx_rel = row.get("PTX Path", "").strip()
        if not ptx_rel:
            continue

        lesson_plan = f"lesson_plans/{row.get('Lesson Plan Path', '').strip()}"
        step = None
        if row.get("Step By Step Guide Exists") == "YES":
            step = f"lesson_plans/{row.get('Step By Step Guide Path', '').strip()}"

        path = source_root / ptx_rel
        content_text = path.read_text(encoding="utf-8")
        orig = content_text

        content_text, removed_count = remove_old_resource_boxes(content_text)
        removed += removed_count

        content_text, upgraded_count = upgrade_lesson_only_resource_boxes(content_text, lesson_plan, step)
        upgraded += upgraded_count

        new_content = insert_axiom_if_missing(content_text, lesson_plan, step)
        if new_content is not None:
            content_text = new_content
            added += 1
            if step is None:
                onlylesson += 1

        if content_text != orig:
            path.write_text(content_text, encoding="utf-8")

    print(
        f"resources added: {added}, only lesson: {onlylesson}, "
        f"removed old: {removed}, upgraded: {upgraded}"
    )
    print("add-resources: done")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Insert/upgrade resource boxes in PTX files")
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
    cmd_add_resources(links_csv_path=args.links_csv, source_dir=args.source_dir)


if __name__ == "__main__":
    main()
