"""CLI coordinator for content-related workflows.

Usage examples:

    python3 -m book_builder.content.cli add-objectives
    python3 -m book_builder.content.cli add-resources
    python3 -m book_builder.content.cli namespace
    python3 -m book_builder.content.cli syllabus-tables
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import add_labels, namespace, objectives, resources, syllabus_tables


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Content utility commands")
    sub = parser.add_subparsers(dest="command")

    add_obj = sub.add_parser("add-objectives", help="insert objectives blocks into PTX files")
    add_obj.add_argument(
        "--links-csv",
        type=Path,
        default=objectives.AUTOMATIC_LINKS_PATH,
        help="Path to Automatic Links CSV",
    )
    add_obj.add_argument("--source-dir", type=Path, default=Path("source"), help="Source directory")

    add_res = sub.add_parser("add-resources", help="insert/upgrade resource boxes for lesson plans")
    add_res.add_argument(
        "--links-csv",
        type=Path,
        default=resources.AUTOMATIC_LINKS_PATH,
        help="Path to Automatic Links CSV",
    )
    add_res.add_argument("--source-dir", type=Path, default=Path("source"), help="Source directory")

    ns = sub.add_parser("namespace", help="add xmlns:xi attribute to subsection/subsubsection tags")
    ns.add_argument("--source-dir", type=Path, default=Path("source"), help="Directory to process")

    gs = sub.add_parser("generate-syllabus", help="create syllabus-alignment.ptx from CSV data")
    gs.add_argument(
        "--links-csv",
        type=Path,
        default=syllabus_tables.AUTOMATIC_LINKS_PATH,
        help="Path to Automatic Links CSV",
    )
    gs.add_argument("--source-dir", type=Path, default=Path("source"), help="Source directory")
    gs.add_argument(
        "--output",
        type=Path,
        default=Path("source") / "syllabus-alignment.ptx",
        help="Output PTX path",
    )

    gl = sub.add_parser("generate-lo", help="create lo-coverage-table.ptx from CSV and outcome data")
    gl.add_argument(
        "--links-csv",
        type=Path,
        default=syllabus_tables.AUTOMATIC_LINKS_PATH,
        help="Path to Automatic Links CSV",
    )
    gl.add_argument(
        "--outcomes-csv",
        type=Path,
        default=syllabus_tables.LEARNING_OUTCOMES_PATH,
        help="Path to Learning Outcomes CSV",
    )
    gl.add_argument(
        "--output",
        type=Path,
        default=Path("source") / "lo-coverage-table.ptx",
        help="Output PTX path",
    )

    st = sub.add_parser("syllabus-tables", help="generate both syllabus and LO coverage tables")
    st.add_argument(
        "--links-csv",
        type=Path,
        default=syllabus_tables.AUTOMATIC_LINKS_PATH,
        help="Path to Automatic Links CSV",
    )
    st.add_argument(
        "--outcomes-csv",
        type=Path,
        default=syllabus_tables.LEARNING_OUTCOMES_PATH,
        help="Path to Learning Outcomes CSV",
    )
    st.add_argument("--source-dir", type=Path, default=Path("source"), help="Source directory")
    st.add_argument(
        "--syllabus-output",
        type=Path,
        default=Path("source") / "syllabus-alignment.ptx",
        help="Syllabus output PTX path",
    )
    st.add_argument(
        "--lo-output",
        type=Path,
        default=Path("source") / "lo-coverage-table.ptx",
        help="Learning outcomes output PTX path",
    )

    addlabels = sub.add_parser("add-labels", help="add xml:id labels to PTX elements")
    addlabels.add_argument(
        "--search-dir",
        dest="search_dir",
        default="source",
        help="Directory or file to process (defaults to ./source)",
    )

    sub.add_parser("all", help="execute the typical content workflow in order")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "add-objectives":
        objectives.cmd_add_objectives(links_csv_path=args.links_csv, source_dir=args.source_dir)
    elif args.command == "add-resources":
        resources.cmd_add_resources(links_csv_path=args.links_csv, source_dir=args.source_dir)
    elif args.command == "namespace":
        namespace.cmd_namespace(source_dir=args.source_dir)
    elif args.command == "generate-syllabus":
        syllabus_tables.cmd_generate_syllabus(
            links_csv_path=args.links_csv,
            source_dir=args.source_dir,
            output_path=args.output,
        )
    elif args.command == "generate-lo":
        syllabus_tables.cmd_generate_lo(
            links_csv_path=args.links_csv,
            outcomes_csv_path=args.outcomes_csv,
            output_path=args.output,
        )
    elif args.command == "syllabus-tables":
        syllabus_tables.cmd_generate_syllabus(
            links_csv_path=args.links_csv,
            source_dir=args.source_dir,
            output_path=args.syllabus_output,
        )
        syllabus_tables.cmd_generate_lo(
            links_csv_path=args.links_csv,
            outcomes_csv_path=args.outcomes_csv,
            output_path=args.lo_output,
        )
    elif args.command == "add-labels":
        add_labels.main(search_dir=getattr(args, "search_dir", None))
    elif args.command == "all":
        objectives.cmd_add_objectives()
        resources.cmd_add_resources()
        namespace.cmd_namespace()
        syllabus_tables.cmd_generate_syllabus()
        syllabus_tables.cmd_generate_lo()
    else:
        parser.error(f"unknown command {args.command}")


if __name__ == "__main__":
    main()
