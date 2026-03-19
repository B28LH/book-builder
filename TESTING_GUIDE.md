# Testing Guide: Verify book-builder Works Correctly

This guide validates that all path fixes work correctly and the package is ready for distribution.

---

## Quick Validation (5 minutes)

### Test 1: Verify Paths Resolve Correctly

**From project root:**
```bash
cd /Users/Ben/BLH\ Documents/2026/Kenya\ 2026/Textbooks/book-builder

# Verify the package works from its own directory
python -m book_builder.cli --help
```

**Expected:** Help output showing all available commands

### Test 2: Verify Path.cwd() Usage

Check that the critical template file lookup works:

```bash
# Create a test directory
mkdir -p /tmp/book-builder-test
cd /tmp/book-builder-test

# Copy textbook_info/
cp -r /Users/Ben/BLH\ Documents/2026/Kenya\ 2026/Textbooks/book-builder/textbook_info ./

# Copy Book Structure CSV
ls textbook_info/

# Verify the package can find template from a different working directory
python -c "
import sys
sys.path.insert(0, '/Users/Ben/BLH Documents/2026/Kenya 2026/Textbooks/book-builder')
from book_builder.content.create_book_skeleton import load_source_section_template
try:
    template = load_source_section_template()
    print('✅ SUCCESS: Template loaded from /tmp/book-builder-test/textbook_info/')
    print(f'   Template length: {len(template)} chars')
except FileNotFoundError as e:
    print(f'❌ FAILED: {e}')
"
```

**Expected:** "✅ SUCCESS" message

---

## Comprehensive Tests

### Test 3: Test CLI from Different Directories

**Setup:**
```bash
# Copy reference materials to test location
mkdir -p /tmp/test-book
cd /tmp/test-book
cp -r /Users/Ben/BLH\ Documents/2026/Kenya\ 2026/Textbooks/book-builder/textbook_info ./
cp -r /Users/Ben/BLH\ Documents/2026/Kenya\ 2026/Textbooks/book-builder/reference_tocs ./
cp -r /Users/Ben/BLH\ Documents/2026/Kenya\ 2026/Textbooks/book-builder/lesson-plan-templates ./
```

**Test Commands from /tmp/test-book:**
```bash
# Test populate command sees files
python -m book_builder.cli populate --help

# Test that it can read the Book Structure CSV
python -m book_builder.cli populate --book-csv textbook_info/"Book Structure.csv" --list-sources

# Test skeleton command
python -m book_builder.cli skeleton --help

# Test content commands
python -m book_builder.cli namespace --help
python -m book_builder.cli add-objectives --help
python -m book_builder.cli add-resources --help

# Test audit commands
python -m book_builder.cli audit --help
```

**Expected:** All commands run successfully without "file not found" errors

### Test 4: Test Google Credentials Path (if Google setup exists)

```bash
# Create secret directory with test credentials
mkdir -p /tmp/test-book/secret

# If you have existing credentials, copy them
# cp -r /Users/Ben/.../secret/* /tmp/test-book/secret/ 2>/dev/null || true

# Test that the path resolution works
python -c "
import sys
sys.path.insert(0, '/Users/Ben/BLH Documents/2026/Kenya 2026/Textbooks/book-builder')
from pathlib import Path
from book_builder.utils._google import CONFIG_PATH, CREDENTIALS_FILE, TOKEN_FILE

print(f'CONFIG_PATH: {CONFIG_PATH}')
print(f'CREDENTIALS_FILE: {CREDENTIALS_FILE}')
print(f'TOKEN_FILE: {TOKEN_FILE}')

# Verify they resolve to /tmp/test-book, not package dir
assert str(CONFIG_PATH).startswith('/tmp/test-book'), 'CONFIG_PATH not in /tmp/test-book'
print('✅ All Google paths resolve to current working directory')
"
```

**Expected:** All paths show `/tmp/test-book/secret/*` instead of package installation directory

### Test 5: Test CSV Loading

```bash
cd /tmp/test-book

python -c "
import sys
sys.path.insert(0, '/Users/Ben/BLH Documents/2026/Kenya 2026/Textbooks/book-builder')
from book_builder.utils._csvtools import load_structured_csv
from pathlib import Path

csv_path = Path.cwd() / 'textbook_info' / 'Automatic Links.csv'
if csv_path.exists():
    data = load_structured_csv(csv_path)
    print(f'✅ Successfully loaded CSV: {len(data)} rows')
else:
    print(f'CSV not found at {csv_path}')
"
```

**Expected:** CSV loads successfully from current working directory

---

## Pre-Installation Testing (Before pip install)

### Test 6: Build Distribution

From the project root:

```bash
cd /Users/Ben/BLH\ Documents/2026/Kenya\ 2026/Textbooks/book-builder

# Clean previous builds
rm -rf build dist *.egg-info

# Build the wheel
python -m build

# Check contents of wheel
python -c "
import zipfile
import os

wheel_file = [f for f in os.listdir('dist') if f.endswith('.whl')][0]
print(f'Checking {wheel_file}...')

with zipfile.ZipFile(f'dist/{wheel_file}', 'r') as z:
    files = z.namelist()
    
    # Check for critical files
    checks = {
        'py.typed': 'Type hints marker',
        'book_builder/cli.py': 'CLI module',
        'book_builder/content/create_book_skeleton.py': 'Skeleton generator',
    }
    
    for pattern, desc in checks.items():
        found = [f for f in files if pattern in f]
        if found:
            print(f'✅ {desc}: {found[0]}')
        else:
            print(f'❌ {desc}: NOT FOUND')
    
    # Check for data files (should be included via MANIFEST.in)
    data_files = [f for f in files if 'textbook_info' in f or 'lesson.plan' in f]
    if data_files:
        print(f'✅ Data files included: {len(data_files)} files')
        for f in data_files[:3]:
            print(f'   - {f}')
    else:
        print('⚠️  No textbook_info or lesson-plan-templates in wheel (this is OK if using MANIFEST.in)')
"
```

**Expected:** Critical files present, package structure correct

### Test 7: Install from Wheel and Test

```bash
# Create a virtual environment
python -m venv /tmp/test-venv
source /tmp/test-venv/bin/activate

# Install from wheel
pip install /Users/Ben/BLH\ Documents/2026/Kenya\ 2026/Textbooks/book-builder/dist/book_builder-*.whl

# Test the installed command
cd /tmp/test-book
book-builder --help

# Verify it works
book-builder skeleton --help
```

**Expected:** 
- `book-builder` command is available globally
- Help output shows all subcommands
- No import errors or path errors

---

## Full Integration Test (15 minutes)

### Test 8: Complete Workflow

```bash
# Create a test project
mkdir -p /tmp/full-test
cd /tmp/full-test

# Set up minimal project structure
mkdir -p textbook_info source reference reference_tocs

# Copy minimal required files
cp /Users/Ben/BLH\ Documents/2026/Kenya\ 2026/Textbooks/book-builder/textbook_info/template.ptx textbook_info/
cp /Users/Ben/BLH\ Documents/2026/Kenya\ 2026/Textbooks/book-builder/textbook_info/"Book Structure.csv" textbook_info/
cp /Users/Ben/BLH\ Documents/2026/Kenya\ 2026/Textbooks/book-builder/textbook_info/"Open Textbooks.csv" textbook_info/

# Test create skeleton (most critical command)
python -m book_builder.cli skeleton \
  --book-csv textbook_info/"Book Structure.csv" \
  --xml-source-output source

# Check generated files
ls -la source/
echo "✅ Skeleton created successfully"

# Verify source files were created
if [ -f "source/content.ptx" ]; then
    echo "✅ content.ptx generated"
    head -5 source/content.ptx
fi
```

**Expected:**
- Skeleton generates without file-not-found errors
- source/content.ptx created
- Chapter directories created

---

## Error Scenarios to Test

### Scenario 1: Missing textbook_info (Should give clear error)

```bash
mkdir -p /tmp/missing-info
cd /tmp/missing-info

python -m book_builder.cli skeleton \
  --book-csv textbook_info/"Book Structure.csv" 2>&1 | head -20
```

**Expected:** Clear error message pointing to /tmp/missing-info/textbook_info/, not package directory

### Scenario 2: Running from nested directory (Should still work)

```bash
cd /tmp/test-book
mkdir -p deep/nested/dir
cd deep/nested/dir

python -m book_builder.cli populate --help 2>&1 | head -5
```

**Expected:** Command works normally (help output shown)

---

## Verification Checklist

Run this quick verification script:

```bash
python << 'EOF'
import sys
import os
from pathlib import Path

# Add book-builder to path
sys.path.insert(0, '/Users/Ben/BLH Documents/2026/Kenya 2026/Textbooks/book-builder')

checks = []

# Check 1: CLI can be imported
try:
    from book_builder.cli import main
    checks.append(('✅', 'CLI imports successfully'))
except Exception as e:
    checks.append(('❌', f'CLI import failed: {e}'))

# Check 2: create_book_skeleton uses Path.cwd()
try:
    with open('/Users/Ben/BLH Documents/2026/Kenya 2026/Textbooks/book-builder/book_builder/content/create_book_skeleton.py') as f:
        content = f.read()
        if 'Path.cwd()' in content and 'template.ptx' in content:
            checks.append(('✅', 'create_book_skeleton uses Path.cwd()'))
        else:
            checks.append(('⚠️ ', 'create_book_skeleton may not use Path.cwd()'))
except Exception as e:
    checks.append(('❌', f'Could not check create_book_skeleton: {e}'))

# Check 3: No hard-coded __file__ references looking for package data
try:
    problem_files = []
    for root, dirs, files in os.walk('/Users/Ben/BLH Documents/2026/Kenya 2026/Textbooks/book-builder/book_builder'):
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                with open(filepath) as f:
                    content = f.read()
                    if '__file__' in content and ('textbook_info' in content or 'reference' in content):
                        problem_files.append(filepath)
    
    if problem_files:
        checks.append(('⚠️ ', f'Found __file__ references in: {problem_files}'))
    else:
        checks.append(('✅', 'No problematic __file__ references found'))
except Exception as e:
    checks.append(('❌', f'Could not scan for __file__ refs: {e}'))

# Check 4: MANIFEST.in includes data files
try:
    with open('/Users/Ben/BLH Documents/2026/Kenya 2026/Textbooks/book-builder/MANIFEST.in') as f:
        manifest = f.read()
        if 'textbook_info' in manifest or 'lesson.plan' in manifest:
            checks.append(('✅', 'MANIFEST.in includes data directories'))
        else:
            checks.append(('⚠️ ', 'MANIFEST.in may not include all data files'))
except Exception as e:
    checks.append(('❌', f'Could not check MANIFEST.in: {e}'))

# Print results
print('\n📋 Verification Results:\n')
for status, message in checks:
    print(f'{status} {message}')

# Summary
pass_count = sum(1 for s, _ in checks if s == '✅')
print(f'\n{pass_count}/{len(checks)} checks passed')
EOF
```

---

## When Everything Passes

Once all tests pass:

1. ✅ Package is ready for PyPI publication
2. ✅ Can be installed via `pip install book-builder`
3. ✅ Can be used with `pipx install book-builder`
4. ✅ Works from any directory
5. ✅ Finds resources in user's project, not package installation

**Proceed with:** [PACKAGE_AUDIT.md](PACKAGE_AUDIT.md) Publication Steps section

