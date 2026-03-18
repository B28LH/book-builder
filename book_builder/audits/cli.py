"""Command-line interface for audit and sync utilities.

Usage examples:

    python3 -m book_builder.audits.cli pull-plans
    python3 -m book_builder.audits.cli validate-paths
    python3 -m book_builder.audits.cli audit-pdfs
    python3 -m book_builder.audits.cli all
"""

from __future__ import annotations

import argparse
import io
import re
import shutil
import sys
from pathlib import Path

from googleapiclient.http import MediaIoBaseDownload

from ..helpers import csvtools, google
from . import audit_questions, reports


@google.retry_on_auth_failure
def cmd_pull_plans(args: argparse.Namespace) -> None:
    print("pull-plans: starting")
    ids = google.load_ids_config()
    folder_id = ids.get("lesson_plans_folder_id")
    if not folder_id:
        print(f"lesson_plans_folder_id not found in {google.CONFIG_PATH}")
        return

    service = google.get_drive_service()

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

    dest = Path(getattr(args, "dest", "assets/lesson_plans"))
    clean = getattr(args, "clean", False)
    if clean and dest.exists():
        print(f"pull-plans: cleaning {dest}")
        shutil.rmtree(dest)

    download_folder(
        folder_id,
        dest,
        only_missing=getattr(args, "new", False),
        file_type=getattr(args, "file_type", ".pdf"),
    )
    print("pull-plans: done")


def cmd_validate_paths(args: argparse.Namespace) -> None:
    print("validate-paths: starting")
    base_dir = getattr(args, "base_dir", None)
    base = Path(base_dir) if base_dir else Path(".")

    if getattr(args, "cached", False):
        print("validate-paths: reading cached CSV")
        rows = csvtools.read_links_csv()
    else:
        print("validate-paths: fetching from sheet")
        rows = reports.fetch_links_from_sheet()

    validated = reports.validate_paths(rows, base)
    csvtools.write_links_csv(validated)
    print(f"validate-paths: processed {len(rows)} rows")

    if getattr(args, "no_write", False):
        print("validate-paths: skipped sheet upload")
    else:
        reports.write_validated_to_sheet(validated)
        print("validate-paths: uploaded results to sheet")

    print("validate-paths: done")


def cmd_audit_pdfs(_: argparse.Namespace) -> None:
    print("audit-pdfs: starting")
    base = Path(".")
    unref = reports.find_unreferenced_pdfs(base)
    if unref:
        print("Unreferenced PDFs:")
        for path in unref:
            print(path)
    else:
        print("All PDFs are referenced.")
    print("audit-pdfs: done")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit utility commands for the project")
    sub = parser.add_subparsers(dest="command")

    pull_parent = argparse.ArgumentParser(add_help=False)
    pull_parent.add_argument(
        "--new", action="store_true", help="only download plans that are not already present"
    )
    pull_parent.add_argument(
        "--clean", action="store_true", help="remove existing lesson plans before downloading"
    )

    validate_parent = argparse.ArgumentParser(add_help=False)
    validate_parent.add_argument("--base-dir", help="root of repo (defaults to current working directory)")
    validate_parent.add_argument(
        "--cached",
        action="store_true",
        help="use locally cached Automatic Links.csv instead of fetching from sheet",
    )
    validate_parent.add_argument(
        "--no-write-sheet",
        action="store_true",
        dest="no_write",
        help="do not upload validation results back to a sheet (default is to write)",
    )

    pull_parser = sub.add_parser("pull-plans", parents=[pull_parent], help="download lesson plans from Drive")
    pull_parser.add_argument(
        "--dest",
        default="assets/lesson_plans",
        help="destination directory for downloaded lesson plans (default: assets/lesson_plans)",
    )
    pull_parser.add_argument(
        "--file-type",
        default=".pdf",
        choices=[".pdf", ".md"],
        help="file type to download (default: .pdf)",
    )

    sub.add_parser(
        "validate-paths",
        parents=[validate_parent],
        help="verify and annotate CSV rows with file existence",
    )
    sub.add_parser("audit-pdfs", help="report lesson-plan PDFs not referenced by any source file")
    sub.add_parser("audit-questions", help="run the STACK/image/pdf audit routines")
    sub.add_parser(
        "all",
        parents=[pull_parent, validate_parent],
        help="execute the typical audit workflow in order",
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "pull-plans":
        cmd_pull_plans(args)
    elif args.command == "validate-paths":
        cmd_validate_paths(args)
    elif args.command == "audit-pdfs":
        cmd_audit_pdfs(args)
    elif args.command == "audit-questions":
        audit_questions.run_audit()
    elif args.command == "all":
        cmd_pull_plans(args)
        cmd_validate_paths(args)
        cmd_audit_pdfs(args)
        audit_questions.run_audit()
    else:
        parser.error(f"unknown command {args.command}")


if __name__ == "__main__":
    main()
