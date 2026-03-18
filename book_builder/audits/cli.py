"""Command-line interface for audit functions

Usage examples:

    python3 -m book_builder.audits.cli pull-plans
    python3 -m book_builder.audits.cli validate-paths
    python3 -m book_builder.audits.cli audit-pdfs
    python3 -m book_builder.audits.cli all
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from book_builder.audits import audit_questions, reports, lesson_plans


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
        lesson_plans.cmd_pull_plans(args)
    elif args.command == "validate-paths":
        lesson_plans.cmd_validate_paths(args)
    elif args.command == "audit-pdfs":
        reports.cmd_audit_pdfs(args)
    elif args.command == "audit-questions":
        audit_questions.run_audit()
    elif args.command == "all":
        lesson_plans.cmd_pull_plans(args)
        lesson_plans.cmd_validate_paths(args)
        reports.cmd_audit_pdfs(args)
        audit_questions.run_audit()
    else:
        parser.error(f"unknown command {args.command}")


if __name__ == "__main__":
    main()
