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
    only_missing: bool = False,
    clean: bool = False,
    dest: Path | str = None,
    file_type: str = ".pdf",
) -> None:
    print("pull-plans: starting")
    if dest is None:
        dest = Path.cwd() / "assets" / "lesson_plans"
    else:
        dest = Path(dest)
    ids = _google.load_ids_config()
    folder_id = ids.get("lesson_plans_folder_id")
    if not folder_id:
        print(f"lesson_plans_folder_id not found in {_google.CONFIG_PATH}")
        return

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
    base_dir: Path | str | None = None,
    cached: bool = False,
    no_write: bool = False,
) -> None:
    print("validate-paths: starting")
    base = Path(base_dir) if base_dir else Path.cwd()

    if cached:
        print("validate-paths: reading cached CSV")
        rows = _csvtools.read_links_csv()
    else:
        print("validate-paths: fetching from sheet")
        rows = reports.fetch_links_from_sheet()

    validated = reports.validate_paths(rows, base)
    _csvtools.write_links_csv(validated)
    print(f"validate-paths: processed {len(rows)} rows")

    if no_write:
        print("validate-paths: skipped sheet upload")
    else:
        reports.write_validated_to_sheet(validated)
        print("validate-paths: uploaded results to sheet")

    print("validate-paths: done")