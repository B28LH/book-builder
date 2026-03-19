#!/usr/bin/env python3
"""Command-line interface for the unified reference population pipeline.

This module is intentionally thin: it parses CLI arguments, builds
`PopulationOptions`, and delegates all work to `run_population()`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from book_builder.populator.populate import PopulationOptions, run_population
from book_builder.content import create_book_skeleton


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(description="Populate reference files from CNXML and/or PreTeXt sources")
    parser.add_argument(
        "--source-format",
        choices=["auto", "cnxml", "pretext"],
        default="auto",
        help="Default is auto: inspect Book Structure resources and dispatch by source type",
    )
    parser.add_argument("--book-csv", type=Path, default=Path("textbook_info/Book Structure.csv"))
    parser.add_argument(
        "--toc-csv",
        type=Path,
        default=Path("reference_tocs/stax-toc.csv"),
        help="CNXML TOC CSV, or explicit TOC CSV when running a single PreTeXt resource",
    )
    parser.add_argument("--reference", type=Path, default=Path("reference"))
    parser.add_argument("--workspace-root", type=Path, default=Path("."))
    parser.add_argument("--open-textbooks-csv", type=Path, default=Path("textbook_info/Open Textbooks.csv"))
    parser.add_argument("--enriched-toc-output", type=Path, default=Path("reference_tocs/stax-toc.enriched.csv"))
    parser.add_argument("--resource", type=str, default=None, help="Resource abbreviation for PreTeXt exports, e.g. ORCCA")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of Book Structure rows processed")
    parser.add_argument("--no-copy-images", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> None:
    """Run the CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()
    
    
    enriched_toc_output = args.enriched_toc_output if args.source_format in {"auto", "cnxml"} else None
    result = run_population(
        PopulationOptions(
            source_format=args.source_format,
            workspace_root=args.workspace_root,
            book_csv=args.book_csv,
            toc_csv=args.toc_csv,
            reference_dir=args.reference,
            open_textbooks_csv=args.open_textbooks_csv,
            enriched_toc_output=enriched_toc_output,
            resource=args.resource,
            limit=args.limit,
            no_copy_images=args.no_copy_images,
            dry_run=args.dry_run,
        )
    )

    


if __name__ == "__main__":
    main()
