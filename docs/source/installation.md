Installation
============

**book-builder** supports Python >= 3.8.

## Installing with `pip`

**book-builder** is available [on PyPI](https://pypi.org/project/book-builder/). Just run

```bash
pip install book-builder
```

## Installing from source

To install **book-builder** from source, first clone [the repository](https://github.com/B28LH/book-builder):

```bash
git clone https://github.com/B28LH/book-builder.git
cd book-builder
```

Then run

```bash
pip install -e .
```

## Installing development dependencies

If you plan to run tests, linting, or docs builds:

```bash
pip install -e .[dev]
```

## Verify installation

Run a quick help check for the main workflows:

```bash
python -m book_builder.create_book_structure --help
python -m book_builder.adapter.cli --help
```

## Optional: local docs build

From the repository root:

```bash
make docs
```

This starts an auto-reloading Sphinx build for `docs/source/`.
