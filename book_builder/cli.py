import argparse
import sys

from audits import lesson_plans, reports, audit_questions


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(description="Commands to help build pretext books, audit content, and adapt open source material.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ## Audits commands
    
    
    pull_plans = subparsers.add_parser("pull-plans", help="Download lesson plans from the Google Drive")
    pull_plans.add_argument(
        "--new", action="store_true", help="only download plans that are not already present"
    )
    pull_plans.add_argument(
        "--clean", action="store_true", help="remove existing lesson plans before downloading"
    )
    pull_plans.add_argument(
        "--dest",
        default="assets/lesson_plans",
        help="destination directory for downloaded lesson plans (default: assets/lesson_plans)",
    )
    pull_plans.add_argument(
        "--file-type",
        default=".pdf",
        choices=[".pdf", ".md"],
        help="file type to download (default: .pdf)",
    )
    
    validate_plans = subparsers.add_parser("validate-plans", help="Verify and annotate CSV rows with file existence")
    validate_plans.add_argument("--base-dir", help="root of repo (defaults to current working directory)")
    validate_plans.add_argument(
        "--cached",
        action="store_true",
        help="use locally cached Automatic Links.csv instead of fetching from sheet",
    )
    validate_plans.add_argument(
        "--no-write-sheet",
        action="store_true",
        dest="no_write",
        help="do not upload validation results back to a sheet (default is to write)",
    )
    
    subparsers.add_parser("audit-pdfs", help="Report lesson-plan PDFs not referenced by any source file")
    
    subparsers.add_parser("audit-questions", help="Run the STACK/image/pdf audit routines")
    
    subparsers.add_parser("audit-full", help="Pull plans, validate, and audit pdfs and questions")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    
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