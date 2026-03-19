from __future__ import annotations

import csv
from pathlib import Path

from book_builder.utils import _google


def _fetch_tab_values(spreadsheet_id: str, tab_name: str) -> list[list[str]]:
    service = _google.get_sheets_service()
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id, range=f"'{tab_name}'").execute()
    return result.get("values", [])


def _write_values_to_csv(values: list[list[str]], output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if values:
            writer.writerows(values)


@_google.retry_on_auth_failure
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

    structure_values = _fetch_tab_values(spreadsheet_id=spreadsheet_id, tab_name=structure_tab)
    syllabus_values = _fetch_tab_values(spreadsheet_id=spreadsheet_id, tab_name=syllabus_tab)

    structure_csv = output_dir / f"{structure_tab}.csv"
    syllabus_csv = output_dir / f"{syllabus_tab}.csv"
    _write_values_to_csv(structure_values, structure_csv)
    _write_values_to_csv(syllabus_values, syllabus_csv)

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
