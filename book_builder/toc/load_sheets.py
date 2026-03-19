from __future__ import annotations

from pathlib import Path

from book_builder.utils import _google, _csvtools


def load_textbook_sheet(
    grade: str,
    output_path: Path | str | None = None,
    structure_tab: str = "Book Structure",
    syllabus_tab: str = "Core Syllabus",
) -> dict[str, Path]:
    """Download textbook tabs for *grade* and cache them as CSV files.

    By default, CSVs are written to ``./textbook_info`` as
    ``Book Structure.csv`` and ``Core Syllabus.csv``.
    """
    ids = _google.load_ids_config()
    try:
        spreadsheet_id = ids["grade"][grade]["textbook_spreadsheet_id"]
    except KeyError:
        raise ValueError(f"Spreadsheet ID not found for grade '{grade}'")

    output_dir = Path(output_path) if output_path is not None else (Path.cwd() / "textbook_info")

    structure_values = _google._fetch_tab_values(spreadsheet_id=spreadsheet_id, tab_name=structure_tab)
    syllabus_values = _google._fetch_tab_values(spreadsheet_id=spreadsheet_id, tab_name=syllabus_tab)

    structure_csv = output_dir / f"{structure_tab}.csv"
    syllabus_csv = output_dir / f"{syllabus_tab}.csv"
    _csvtools._write_values_to_csv(structure_values, structure_csv)
    _csvtools._write_values_to_csv(syllabus_values, syllabus_csv)

    return {
        "structure": structure_csv,
        "syllabus": syllabus_csv,
    }


def cmd_load_textbook_sheet(
    *,
    grade: str,
    output_dir: Path | str | None = None,
    structure_tab: str = "Book Structure",
    syllabus_tab: str = "Core Syllabus",
) -> None:
    print("load-textbook-sheet: starting")
    outputs = load_textbook_sheet(
        grade=grade,
        output_path=output_dir,
        structure_tab=structure_tab,
        syllabus_tab=syllabus_tab,
    )
    print(f"load-textbook-sheet: wrote {outputs['structure']}")
    print(f"load-textbook-sheet: wrote {outputs['syllabus']}")
    print("load-textbook-sheet: done")
