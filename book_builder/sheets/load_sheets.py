from __future__ import annotations

from pathlib import Path

from book_builder.utils import _google, _csvtools


def load_textbook_sheet(
    grade: str,
    output_dir: Path,
    structure_tab: str = "Book Structure",
    syllabus_tab: str = "Learning Outcomes",
):
    """Download textbook tabs for *grade* and cache them as CSV files.

    By default, CSVs are written to ``./textbook_info`` as
    ``Book Structure.csv`` and ``Learning Outcomes.csv``.
    """
    ids = _google.load_ids_config()
    try:
        spreadsheet_id = ids["grade"][grade]["textbook_spreadsheet_id"]
    except KeyError:
        raise ValueError(f"Spreadsheet ID not found for grade '{grade}'")
    
    print("load-textbook-sheet: starting")

    structure_values = _google._fetch_tab_values(spreadsheet_id=spreadsheet_id, tab_name=structure_tab)
    syllabus_values = _google._fetch_tab_values(spreadsheet_id=spreadsheet_id, tab_name=syllabus_tab)

    structure_csv = output_dir / f"{structure_tab}.csv"
    syllabus_csv = output_dir / f"{syllabus_tab}.csv"
    _csvtools._write_values_to_csv(structure_values, structure_csv)
    _csvtools._write_values_to_csv(syllabus_values, syllabus_csv)
    
    print(f"load-textbook-sheet: wrote {structure_csv}")
    print(f"load-textbook-sheet: wrote {syllabus_csv}")
    
    
def load_open_textbooks_sheet(
    output_dir: Path
):
    """Download open resources spreadsheet

    By default, CSVs are written to ``./textbook_info`` as
    ``Book Structure.csv`` and ``Learning Outcomes.csv``.
    """
    ids = _google.load_ids_config()
    try:
        spreadsheet_id = ids["open_textbooks_spreadsheet_id"]
    except KeyError:
        raise ValueError(f"Spreadsheet ID not found for open textbooks")
    
    print("load-open-textbooks-sheet: starting")

    open_textbook_values = _google._fetch_tab_values(spreadsheet_id=spreadsheet_id, tab_name="Open Textbooks")

    open_textbook_csv = output_dir / f"Open Textbooks.csv"
    _csvtools._write_values_to_csv(open_textbook_values, open_textbook_csv)

    print(f"load-open-textbooks-sheet: wrote {open_textbook_csv}")