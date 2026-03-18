# **book-builder**

Build and maintain a PreTeXt textbook pipeline from mixed open-source source formats.

`book-builder` helps you:

- generate textbook folder/file structure from planning CSVs,
- export source TOCs to CSV for matching,
- and populate reference sections with adapted content.

```{toctree}
:maxdepth: 2
:hidden:
:caption: Getting started

installation
overview
```

```{toctree}
:hidden:
:caption: Development

CHANGELOG
CONTRIBUTING
License <https://raw.githubusercontent.com/B28LH/book-builder/main/LICENSE>
GitHub Repository <https://github.com/B28LH/book-builder>
```

## Quick links

- [Installation](installation)
- [Overview and workflows](overview)
- [Repository README](https://github.com/B28LH/book-builder/blob/main/README.md)

## Typical first run

1. Install dependencies.
2. Generate the source/reference structure from `textbook_info/Book Structure.csv`.
3. Export TOCs (CNXML and/or PreTeXt) into `reference_tocs/`.
4. Run the population pipeline.

See [Overview and workflows](overview) for exact commands.

## Indices and tables

```{eval-rst}
* :ref:`genindex`
* :ref:`modindex`
```
