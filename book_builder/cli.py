""" Command-line interface for book builder utilities. """

import argparse
from pathlib import Path

from book_builder.audits import lesson_plans, reports, audit_questions
from book_builder.populator import populate
from book_builder.content import add_labels, create_book_skeleton, namespace, objectives, resources, syllabus_tables
from book_builder.toc import create_pretext_toc, create_stax_toc


def build_populate_parser(subparsers):
    """ Add populate-related subcommands to the given subparsers object. """
    
    populate = subparsers.add_parser("populate", help="Using the Book Structure and TOC CSVs, populate reference folder with converted content from CNXML and/or PreTeXt sources")
    
    populate.add_argument(
        "--source-format",
        choices=["auto", "cnxml", "pretext"],
        default="auto",
        help="Default is auto: inspect Book Structure resources and dispatch by source type",
    )
    populate.add_argument(
        "--book-csv", 
        type=Path, 
        default=Path("textbook_info") / "Book Structure.csv"
    )
    populate.add_argument(
        "--toc-csv",
        type=Path,
        default=Path("reference_tocs/stax-toc.csv"),
        help="CNXML TOC CSV, or explicit TOC CSV when running a single PreTeXt resource",
    )
    populate.add_argument(
        "--reference", 
        type=Path, 
        default=Path("reference"))
    populate.add_argument(
        "--workspace-root", 
        type=Path, 
        default=Path(".")
    )
    populate.add_argument(
        "--open-textbooks-csv", 
        type=Path, 
        default=Path("textbook_info/Open Textbooks.csv")
    )
    populate.add_argument(
        "--enriched-toc-output", 
        type=Path, 
        default=Path("reference_tocs/stax-toc.enriched.csv")
    )
    populate.add_argument(
        "--resource", 
        type=str, 
        default=None, 
        help="Resource abbreviation for PreTeXt exports, e.g. ORCCA")
    populate.add_argument(
        "--limit", 
        type=int, 
        default=None, 
        help="Limit number of Book Structure rows processed"
    )
    populate.add_argument(
        "--no-copy-images", 
        action="store_true"
    )
    populate.add_argument(
        "--dry-run", 
    action="store_true")
    
    

def build_audit_parser(subparsers):
    """Add audit-related subcommands to the given subparsers object."""

    pull_plans = subparsers.add_parser("pull-plans", help="Download lesson plans from the Google Drive")
    pull_plans.add_argument("--new", action="store_true", help="only download plans that are not already present")
    pull_plans.add_argument("--clean", action="store_true", help="remove existing lesson plans before downloading")
    pull_plans.add_argument("--dest", default="assets/lesson_plans", help="destination directory for downloaded lesson plans (default: assets/lesson_plans)")
    pull_plans.add_argument("--file-type", default=".pdf", choices=[".pdf", ".md"], help="file type to download (default: .pdf)")

    validate_paths = subparsers.add_parser("validate-paths", help="Verify and annotate CSV rows with file existence")
    validate_paths.add_argument("--base-dir", help="root of repo (defaults to current working directory)")
    validate_paths.add_argument("--cached", action="store_true", help="use locally cached Automatic Links.csv instead of fetching from sheet")
    validate_paths.add_argument("--no-write-sheet", action="store_true", dest="no_write", help="do not upload validation results back to a sheet (default is to write)")

    subparsers.add_parser("audit-pdfs", help="Report lesson-plan PDFs not referenced by any source file")

    audit_questions_parser = subparsers.add_parser("audit-questions", help="Run the STACK/image/pdf audit routines")
    audit_questions_parser.add_argument("--output-folder", type=Path, default=Path("textbook_info"), help="folder to write audit outputs (like orphaned_ptx) to; defaults to 'textbook_info'")

    subparsers.add_parser("audit", help="Pull plans, validate, and audit pdfs and questions")


def build_content_parser(subparsers):
    """ Adds content-related subcommands to the given subparsers object. """

    skeleton = subparsers.add_parser("skeleton", help="generate empty PreTeXt structure files from Book Structure CSV")
    skeleton.add_argument(
        "--csv",
        type=Path,
        default=Path("textbook_info/Book Structure.csv"),
        help="Path to the Book Structure CSV",
    )
    skeleton.add_argument(
        "--source",
        type=Path,
        default=Path("source"),
        help="Path to the PreTeXt source directory",
    )
    skeleton.add_argument(
        "--reference",
        type=Path,
        default=Path("reference"),
        help="Path to the generated reference directory",
    )

    add_obj = subparsers.add_parser("add-objectives", help="insert objectives blocks into PTX files")
    add_obj.add_argument(
        "--links-csv",
        type=Path,
        default=objectives.AUTOMATIC_LINKS_PATH,
        help="Path to Automatic Links CSV",
    )
    add_obj.add_argument(
        "--source-dir",
        type=Path,
        default=Path("source"),
        help="Source directory",
    )

    add_resources = subparsers.add_parser("add-resources", help="insert/upgrade resource boxes for lesson plans")
    add_resources.add_argument(
        "--links-csv",
        type=Path,
        default=resources.AUTOMATIC_LINKS_PATH,
        help="Path to Automatic Links CSV",
    )
    add_resources.add_argument(
        "--source-dir",
        type=Path,
        default=Path("source"),
        help="Source directory",
    )

    namespace = subparsers.add_parser("namespace", help="add xmlns:xi attribute to subsection/subsubsection tags")
    namespace.add_argument(
        "--source-dir",
        type=Path,
        default=Path("source"),
        help="Directory to process",
    )

    generate_syllabus = subparsers.add_parser("generate-syllabus", help="create syllabus-alignment.ptx from CSV data")
    generate_syllabus.add_argument(
        "--links-csv",
        type=Path,
        default=syllabus_tables.AUTOMATIC_LINKS_PATH,
        help="Path to Automatic Links CSV",
    )
    generate_syllabus.add_argument(
        "--source-dir",
        type=Path,
        default=Path("source"),
        help="Source directory",
    )
    generate_syllabus.add_argument(
        "--output",
        type=Path,
        default=Path("source") / "syllabus-alignment.ptx",
        help="Output PTX path",
    )

    generate_lo = subparsers.add_parser("generate-lo", help="create lo-coverage-table.ptx from CSV and outcome data")
    generate_lo.add_argument(
        "--links-csv",
        type=Path,
        default=syllabus_tables.AUTOMATIC_LINKS_PATH,
        help="Path to Automatic Links CSV",
    )
    generate_lo.add_argument(
        "--outcomes-csv",
        type=Path,
        default=syllabus_tables.LEARNING_OUTCOMES_PATH,
        help="Path to Learning Outcomes CSV",
    )
    generate_lo.add_argument(
        "--output",
        type=Path,
        default=Path("source") / "lo-coverage-table.ptx",
        help="Output PTX path",
    )

    syllabus = subparsers.add_parser("syllabus-tables", help="generate both syllabus and LO coverage tables")
    syllabus.add_argument(
        "--links-csv",
        type=Path,
        default=syllabus_tables.AUTOMATIC_LINKS_PATH,
        help="Path to Automatic Links CSV",
    )
    syllabus.add_argument(
        "--outcomes-csv",
        type=Path,
        default=syllabus_tables.LEARNING_OUTCOMES_PATH,
        help="Path to Learning Outcomes CSV",
    )
    syllabus.add_argument(
        "--source-dir",
        type=Path,
        default=Path("source"),
        help="Source directory",
    )
    syllabus.add_argument(
        "--syllabus-output",
        type=Path,
        default=Path("source") / "syllabus-alignment.ptx",
        help="Syllabus output PTX path",
    )
    syllabus.add_argument(
        "--lo-output",
        type=Path,
        default=Path("source") / "lo-coverage-table.ptx",
        help="Learning outcomes output PTX path",
    )

    add_labels = subparsers.add_parser("add-labels", help="add xml:id labels to PTX elements")
    add_labels.add_argument(
        "--search-dir",
        dest="search_dir",
        default="source",
        help="Directory or file to process (defaults to ./source)",
    )

    subparsers.add_parser("content", help="execute the typical content workflow in order")
    
    
def build_toc_parser(subparsers):
    """Add TOC-related subcommands to the given subparsers object."""

    pretext_toc = subparsers.add_parser(
        "pretext-toc", 
        help="Export PreTeXt TOC to CSV"
    )
    pretext_toc.add_argument(
        "root", 
        type=Path, 
        help="Path to the starting PreTeXt/PTX file"
    )
    pretext_toc.add_argument(
        "--output-name", 
        type=Path, 
        default=None, 
        help="Output CSV name (defaults to <root-stem>-toc.csv)"
    )
    pretext_toc.add_argument(
        "--relative-to", 
        type=Path, 
        default=None, 
        help="Base directory used for source_path values"
    )
    pretext_toc.add_argument(
        "--resource-name", 
        type=str, 
        default=None, 
        help="Short identifier prepended to every generated node ID (defaults to root stem uppercased)"
    )
    pretext_toc.add_argument(
        "--mapping-output", 
        type=Path, 
        default=None, 
        help="Path for the ID-mapping CSV (defaults to <stem>-id-mapping.csv beside the TOC output)"
    )

    stax_toc = subparsers.add_parser(
        "stax-toc", 
        help="Export STAX collection TOC to CSV")
    stax_toc.add_argument(
        "resource_folder", 
        type=Path, 
        help="Location of the resource folder containing the collection XML and modules (e.g. adapted-worls/PREALG)"
    )
    stax_toc.add_argument(
        "collection_name", 
        type=str, 
        help="Name of the collection XML file (e.g. prealgebra-2e for prealgebra-2e.collection.xml). Assumed to be in resource-folder/collections/"
    )
    stax_toc.add_argument(
        "--output-name", 
        type=Path, 
        default=None, 
        help="CSV output name (defaults to <collection-basename>-toc.csv)"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Commands to help build pretext books, audit content, and adapt open source material.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    build_populate_parser(subparsers)
    build_audit_parser(subparsers)
    build_content_parser(subparsers)
    build_toc_parser(subparsers)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "populate":
        result = populate.run_population(
            populate.PopulationOptions(
                source_format=args.source_format,
                workspace_root=args.workspace_root,
                book_csv=args.book_csv,
                toc_csv=args.toc_csv,
                reference_dir=args.reference,
                open_textbooks_csv=args.open_textbooks_csv,
                enriched_toc_output=args.enriched_toc_output if args.source_format in {"auto", "cnxml"} else None,
                resource=args.resource,
                limit=args.limit,
                no_copy_images=args.no_copy_images,
                dry_run=args.dry_run,
            )
        )
        
        populate.print_results(result)
    elif args.command == "pull-plans":
        lesson_plans.cmd_pull_plans(
            only_missing=args.new,
            clean=args.clean,
            dest=args.dest,
            file_type=args.file_type,
        )
    elif args.command == "validate-paths":
        lesson_plans.cmd_validate_paths(
            base_dir=args.base_dir,
            cached=args.cached,
            no_write=args.no_write,
        )
    elif args.command == "audit-pdfs":
        reports.cmd_audit_pdfs()
    elif args.command == "audit-questions":
        audit_questions.run_audit(output_folder=args.output_folder)
    elif args.command == "audit":
        lesson_plans.cmd_pull_plans()
        lesson_plans.cmd_validate_paths()
        reports.cmd_audit_pdfs()
        audit_questions.run_audit(output_folder=Path("textbook_info"))
    elif args.command == "skeleton":
        create_book_skeleton.main(args.csv.resolve(), args.source.resolve(), args.reference.resolve())
    elif args.command == "add-objectives":
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
    elif args.command == "content":
        objectives.cmd_add_objectives()
        resources.cmd_add_resources()
        namespace.cmd_namespace()
        syllabus_tables.cmd_generate_syllabus()
        syllabus_tables.cmd_generate_lo()
    elif args.command == "pretext-toc":
        row_count = create_pretext_toc.run_pretext_toc(
            root=args.root,
            output_name=args.output_name,
            relative_to=args.relative_to,
            resource_name=args.resource_name,
            mapping_output=args.mapping_output,
        )
        output_path = Path("reference_tocs") / (args.output_name or Path(f"{args.root.stem}-toc.csv"))
        print(f"Wrote {row_count} TOC rows to {output_path}")
    elif args.command == "stax-toc":
        output_path = create_stax_toc.run_stax_toc(
            resource_folder=args.resource_folder,
            collection_name=args.collection_name,
            output_name=args.output_name,
        )
        print(f"Wrote TOC CSV: {output_path}")
    else:
        parser.error(f"unknown command {args.command}")


if __name__ == "__main__":
    main()