Overview
========

`book-builder` is a Python package for producing a PreTeXt textbook from structured planning metadata and open-source source books.

It is designed around a simple idea: keep your own book structure in CSV, then automate repetitive source lookup, extraction, conversion, and section population.

Core components
---------------

- **Structure generation** (`book_builder.create_book_structure`)
	- Reads `textbook_info/Book Structure.csv`.
	- Creates chapter/section files in both `source/` and `reference/`.
	- Writes top-level include file(s) such as `content.ptx`.

- **TOC export** (`book_builder.toc.*`)
	- `create_stax_toc`: CNXML collection/module/section export.
	- `create_pretext_toc`: PreTeXt `xi:include` traversal export (+ ID mapping CSV).

- **Population pipeline** (`book_builder.adapter.cli`)
	- Matches Book Structure rows to source TOC entries.
	- Converts source content blocks to target-ready fragments.
	- Injects content into target reference sections with attribution support.

Typical workflow
----------------

1. **Generate structure**

	 ```bash
	 python -m book_builder.create_book_structure
	 ```

2. **Export source TOCs**

	 - CNXML:

		 ```bash
		 python -m book_builder.toc.create_stax_toc <collection.xml> --modules-root <modules-dir>
		 ```

	 - PreTeXt:

		 ```bash
		 python -m book_builder.toc.create_pretext_toc <root.ptx> --resource-name <RESOURCE>
		 ```

3. **Populate references**

	 ```bash
	 python -m book_builder.adapter.cli --source-format auto
	 ```

Key inputs and outputs
----------------------

- Inputs:
	- `textbook_info/Book Structure.csv`
	- `textbook_info/Open Textbooks.csv`
	- source materials under `adapted-works/`
	- TOC CSVs in `reference_tocs/`

- Outputs:
	- generated/updated files in `source/` and `reference/`
	- enriched TOC CSV (CNXML flow)
	- optional ID map CSV (PreTeXt TOC flow)

Helpful flags
-------------

- `--limit N`: run a small subset while testing.
- `--dry-run`: evaluate matching without writing content.
- `--no-copy-images`: skip image copy operations.

For full option lists:

```bash
python -m book_builder.create_book_structure --help
python -m book_builder.toc.create_stax_toc --help
python -m book_builder.toc.create_pretext_toc --help
python -m book_builder.adapter.cli --help
```

