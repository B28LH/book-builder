# Quick Reference: PyPI Deployment Checklist

Use this checklist when you're ready to publish to PyPI.

---

## Pre-Deployment (Do Once)

### Setup PyPI Authentication
```bash
# Install twine (if not already installed)
pip install twine build

# Create ~/.pypirc with your credentials (see PyPI docs for details)
# Set up API tokens for security (recommended over passwords)
```

### Verify Code Quality
```bash
cd /Users/Ben/BLH\ Documents/2026/Kenya\ 2026/Textbooks/book-builder

# Run linter
python -m ruff check book_builder

# Run type checker
python -m mypy book_builder

# Run tests
python -m pytest tests/

# Format check
python -m black --check book_builder
```

---

## Publication Steps

### Step 1: Update Version
```bash
# Edit book_builder/version.py with new version
# Example: VERSION = "0.1.0"
nano book_builder/version.py

# Git commit
git add book_builder/version.py
git commit -m "Bump version to 0.1.0"
```

### Step 2: Update Changelog
```bash
# Add entry to CHANGELOG.md
# Example entry:
# ## [0.1.0] - 2026-03-19
# ### Added
# - Initial PyPI release
# - Full path resolution fixes for pipx compatibility
# ### Changed
# - All paths now resolve via Path.cwd()
# ### Fixed
# - Hard-coded paths no longer look to package installation directory

git add CHANGELOG.md
git commit -m "Update CHANGELOG for 0.1.0"
```

### Step 3: Build Distribution
```bash
# Clean previous builds
rm -rf build dist *.egg-info

# Build wheel and source distribution
python -m build

# Verify builds
ls -lh dist/
# Should show:
#   - book_builder-0.1.0-py3-none-any.whl
#   - book_builder-0.1.0.tar.gz
```

### Step 4: Check Distribution
```bash
# Validate distribution files
twine check dist/*

# Should output:
# Checking dist/book_builder-0.1.0-py3-none-any.whl: PASSED
# Checking dist/book_builder-0.1.0.tar.gz: PASSED
```

### Step 5: Test on TestPyPI (First Time Only)
```bash
# Upload to test server
twine upload --repository testpypi dist/*
# Enter username: __token__
# Enter password: pypi-... (your token)

# Install from test server (in a fresh venv)
python -m venv /tmp/test-install
source /tmp/test-install/bin/activate
pip install --index-url https://test.pypi.org/simple/ book-builder

# Test it works
book-builder --help
book-builder skeleton --help

# Deactivate
deactivate
```

### Step 6: Tag Release
```bash
# Create git tag
git tag -a v0.1.0 -m "Release version 0.1.0"

# Push tag
git push origin v0.1.0
```

### Step 7: Upload to Production PyPI
```bash
# Upload to PyPI
twine upload dist/*
# Enter username: __token__
# Enter password: pypi-... (your token)

# Should output:
# Uploading book_builder-0.1.0-py3-none-any.whl [100%]
# Uploading book_builder-0.1.0.tar.gz [100%]
```

### Step 8: Verify on PyPI
1. Visit: https://pypi.org/project/book-builder/
2. Verify version appears
3. Check that description and homepage are correct
4. Verify Python version requirement shows "≥ 3.12"

---

## Post-Deployment Testing

### Test Installation Methods
```bash
# Method 1: pip install (in fresh venv)
python -m venv /tmp/pip-test
source /tmp/pip-test/bin/activate
pip install book-builder
book-builder --help
deactivate

# Method 2: pipx install (if you have pipx)
pipx install book-builder
book-builder --help
pipx uninstall book-builder
```

### Test Package Functionality
```bash
# Create test project
mkdir -p /tmp/final-test
cd /tmp/final-test

# Copy test data
cp -r /Users/Ben/BLH\ Documents/2026/Kenya\ 2026/Textbooks/book-builder/textbook_info ./

# Test main command
book-builder skeleton --book-csv textbook_info/"Book Structure.csv"

# Verify files created
ls source/content.ptx && echo "✅ Success!"
```

---

## Subsequent Releases

For each new release:

1. Update `book_builder/version.py`
2. Update `CHANGELOG.md`
3. `python -m build`
4. `twine check dist/*`
5. `twine upload dist/*`
6. `git tag -a v<version> -m "Release version <version>"`
7. `git push origin v<version>`

---

## If Something Goes Wrong

### Build Failed
```bash
# Clean everything and try again
rm -rf build dist *.egg-info
python -m build
twine check dist/*
```

### TestPyPI Upload Failed
- Check credentials in ~/.pypirc
- Verify version doesn't already exist on TestPyPI (versions can't be reused)
- Try uploading just the wheel first: `twine upload --repository testpypi dist/*.whl`

### Production Upload Failed
- Don't panic! Nothing is published until you see the success message
- Check authentication token is valid
- Verify you're not reusing an existing version

### Package Doesn't Work After Installation
- Run: `pip show -f book-builder` to see where it was installed
- Check that data files are included: `unzip -l $(pip show -f book-builder | grep Location)`
- Verify MANIFEST.in includes textbook_info/ and lesson-plan-templates/

---

## Rollback (If Critical Issue Found)

If you need to yank a version (mark as broken):

```bash
# You can yank versions from https://pypi.org/project/book-builder/
# Go to "Release history" → click version → "Yank release"
# This tells pip/pipx not to install it by default

# Users with the bad version should:
# 1. pip install book-builder --upgrade (to get next good version)
# 2. Or pipx upgrade book-builder
```

---

## Key Resources

- **PyPI Help:** https://pypi.org/help/
- **Python Packaging Guide:** https://packaging.python.org/
- **Twine Docs:** https://twine.readthedocs.io/
- **setuptools Guide:** https://setuptools.pypa.io/
- **This Audit:** See [PACKAGE_AUDIT.md](PACKAGE_AUDIT.md)
- **Testing Guide:** See [TESTING_GUIDE.md](TESTING_GUIDE.md)

---

## Version History

| Version | Date | Status | Notes |
|---------|------|--------|-------|
| 0.1.0 | TBD | Ready | Initial PyPI release with path fixes |

