# book-builder

Utilities for building a PreTeXt textbook workflow from mixed open-source inputs (CNXML and PreTeXt), with support for:

- generating chapter/section skeleton files from curriculum CSVs,
- exporting source tables of contents to normalized CSV,
- and populating reference sections with attributed adapted content.

This repository is tuned for practical textbook production: it combines metadata-driven matching (`textbook_info/Book Structure.csv`) with source adapters and file-safe post-processing.

## What this project does

At a high level, `book-builder` helps you move from planning spreadsheets and source textbooks to a structured PreTeXt book in your workspace.

Core capabilities:

1. **Create a book skeleton**
	 - Reads a Book Structure CSV and creates:
		 - chapter folders,
		 - section templates,
		 - `source/content.ptx` and `reference/content.ptx` include trees.

2. **Export TOCs from source books**
	 - CNXML flow: extract collection/module/section structure to CSV.
	 - PreTeXt flow: resolve `xi:include` trees and export a flattened structural TOC CSV.

3. **Populate reference files**
	 - Matches Book Structure rows to source TOC entries.
	 - Converts source content fragments into PreTeXt-ready blocks.
	 - Injects content into target reference sections with attribution and cleanup passes.

## Repository layout (important folders)

- `book_builder/` — Python package code
	- `create_book_structure.py` — generate source/reference skeleton files
	- `toc/` — TOC exporters for CNXML and PreTeXt
	- `adapter/` — matching, conversion, injection, and orchestration pipeline
- `textbook_info/` — input planning metadata (`Book Structure.csv`, `Open Textbooks.csv`)
- `reference_tocs/` — generated TOC CSVs and ID maps
- `source/` — your authoring tree
- `reference/` — generated/updated adapted reference content
- `adapted-works/` — local copies of upstream source books

## Requirements

- Python **3.8+**

## Installation

### Install from PyPI

```bash
pip install book-builder
```

### Install for development

```bash
git clone https://github.com/B28LH/book-builder.git
cd book-builder
pip install -e .[dev]
```

## Quick start (easy entry)

From the repository root:

1. **Generate/refresh book structure from CSV**

```bash
python -m book_builder.create_book_structure \
	--csv "textbook_info/Book Structure.csv" \
	--source source \
	--reference reference
```

2. **(If needed) export a CNXML TOC**

```bash
python -m book_builder.toc.create_stax_toc \
	adapted-works/PREALG/collections/prealgebra.collection.xml \
	--modules-root adapted-works/PREALG/modules \
	--output-name stax-toc.csv
```

3. **(If needed) export a PreTeXt TOC**

```bash
python -m book_builder.toc.create_pretext_toc \
	adapted-works/ORCCA/src/orcca.ptx \
	--output-name orcca-toc.csv \
	--resource-name ORCCA
```

4. **Run the population pipeline**

```bash
python -m book_builder.adapter.cli --source-format auto
```

Use `--source-format cnxml` or `--source-format pretext --resource ORCCA` when you want one specific flow.

## Main CLI workflows

### A) Generate structure only

```bash
python -m book_builder.create_book_structure --help
```

### B) Export TOC CSVs only

```bash
python -m book_builder.toc.create_stax_toc --help
python -m book_builder.toc.create_pretext_toc --help
```

### C) Populate reference sections from sources

```bash
python -m book_builder.adapter.cli --help
```

Common options:

- `--limit N` — process only the first `N` valid Book Structure rows (useful while testing).
- `--dry-run` — run matching pipeline without writing content.
- `--no-copy-images` — skip image copy operations.

## Development commands

Use the provided Makefile targets:

```bash
make run-checks   # isort, black, ruff, mypy, pytest
make docs         # local Sphinx autobuild
make build        # package build artifacts
```

## Documentation

Project docs live in `docs/source/`.

- Start page: `docs/source/index.md`
- Installation: `docs/source/installation.md`
- Overview: `docs/source/overview.md`

To build docs locally:

```bash
make docs
```

## Notes and troubleshooting

- If `source/` or `reference/` is missing, the adapter CLI can trigger structure generation first.
- If PreTeXt TOC export fails on malformed XML comment closers (`-->`), the parser includes a minimal sanitization retry.
- Keep `textbook_info/Open Textbooks.csv` up to date, especially source type and resource abbreviations used in Book Structure rows.

## License

This project is licensed under the terms in [LICENSE](LICENSE).
