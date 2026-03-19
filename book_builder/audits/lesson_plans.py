from __future__ import annotations

import io
import re
import shutil
from pathlib import Path

from book_builder.utils import _csvtools, _google
from googleapiclient.http import MediaIoBaseDownload
from book_builder.audits import reports


@_google.retry_on_auth_failure
def cmd_pull_plans(
    *,
    grade: str,
    only_missing: bool = False,
    clean: bool = False,
    dest: Path | None = None,
    file_type: str = ".pdf",
) -> None:
    print("pull-plans: starting")
    if dest is None:
        dest = Path.cwd() / "assets" / "lesson_plans"
    else:
        dest = Path(dest)
    ids = _google.load_ids_config()
    
    try:
        folder_id = ids["grade"][grade]["lesson_plans_folder_id"]
    except KeyError:
        raise ValueError(f"Lesson plans folder ID not found for grade '{grade}'")

    service = _google.get_drive_service()

    def sanitize_filename(name: str) -> str:
        cleaned = name.rstrip().lower()
        cleaned = re.sub(r"[,';:]", "", cleaned)
        cleaned = re.sub(r"\s+", "-", cleaned)
        return cleaned

    def download_folder(folder_id: str, local_path: Path, only_missing: bool, file_type: str) -> None:
        if file_type == ".pdf":
            mime_type = "application/pdf"
        elif file_type == ".md":
            mime_type = "text/markdown"
        else:
            raise ValueError(f"Unsupported file type: {file_type}")

        if not local_path.exists():
            local_path.mkdir(parents=True)

        results = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="files(id, name, mimeType)",
        ).execute()
        items = results.get("files", [])

        for item in items:
            cleaned = sanitize_filename(item["name"])
            path = local_path / cleaned
            if item["mimeType"] == "application/vnd.google-apps.folder":
                download_folder(item["id"], path, only_missing, file_type)
            elif item["mimeType"] == "application/vnd.google-apps.document":
                downloaded_path = path.with_suffix(file_type)
                if only_missing and downloaded_path.exists():
                    print(f"Skipping (already exists): {downloaded_path}")
                    continue

                request = service.files().export_media(fileId=item["id"], mimeType=mime_type)
                fh = io.FileIO(str(downloaded_path), "wb")
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                print(f"Downloaded: {downloaded_path.name}")

    dest_path = dest if isinstance(dest, Path) else Path(dest)
    if clean and dest_path.exists():
        print(f"pull-plans: cleaning {dest_path}")
        shutil.rmtree(dest_path)

    download_folder(
        folder_id,
        dest_path,
        only_missing=only_missing,
        file_type=file_type,
    )
    print("pull-plans: done")


def cmd_validate_paths(
    *,
    grade: str | None = None,
    base_dir: Path | str | None = None,
    cached: bool = False,
    no_write: bool = False,
) -> None:
    print("validate-paths: starting")
    base = Path(base_dir) if base_dir else Path.cwd()

    if cached:
        print("validate-paths: reading cached CSV")
        rows = _csvtools.read_links_csv()
    elif grade is not None:
        print("validate-paths: fetching from sheet")
        
        ids = _google.load_ids_config()
        try:
            spreadsheet_id = ids["grade"][grade]["textbook_spreadsheet_id"]
        except KeyError:
            raise ValueError(f"Spreadsheet ID not found for grade '{grade}'")
        
        sheet = _google._fetch_tab_values(spreadsheet_id, "'Automatic Links'")
        if not sheet:
            raise ValueError(f"No data found in 'Automatic Links' sheet for grade '{grade}'")
        headers = sheet[0]
        rows_data = sheet[1:]
        rows = [dict(zip(headers, row)) for row in rows_data]
    else:
        raise ValueError("Either --cached or --grade must be specified")

    validated = reports.validate_paths(rows, base)
    _csvtools.write_links_csv(validated)
    print(f"validate-paths: processed {len(rows)} rows")

    if no_write:
        print("validate-paths: skipped sheet upload")
    elif grade is not None:
        _google.write_validated_to_sheet(grade, validated)
        print("validate-paths: uploaded results to sheet")
    else:
        raise ValueError("Grade must be specified to upload results to sheet")

    print("validate-paths: done")