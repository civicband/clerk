# Testing Guide

This guide explains how to write and run tests for Clerk.

## Test Organization

Clerk uses pytest with a comprehensive test suite:

```
tests/
├── conftest.py              # Shared fixtures and configuration
├── test_utils.py            # Tests for utils.py
├── test_cli.py              # Tests for CLI commands
├── test_hookspecs.py        # Tests for plugin system integration
├── test_integration.py      # End-to-end integration tests
├── fixtures/                # Sample data
│   ├── sample_sites.json
│   └── sample_text_files/
└── mocks/                   # Mock implementations
    ├── mock_fetchers.py
    └── mock_plugins.py
```

## Running Tests

### Basic Usage

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific file
pytest tests/test_cli.py

# Run specific test
pytest tests/test_cli.py::TestBuildTableFromText::test_build_table_from_text_creates_records

# Run tests matching a pattern
pytest -k "test_build"
```

### Test Markers

Tests are organized with markers:

```bash
# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration
```

### Coverage

```bash
# Run with coverage
pytest --cov

# Generate HTML coverage report
pytest --cov --cov-report=html

# View coverage report
open htmlcov/index.html
```

## Writing Tests

### Unit Tests

Unit tests test individual functions in isolation with mocked dependencies:

```python
import pytest
from clerk.cli import build_table_from_text

@pytest.mark.unit
def test_build_table_from_text_creates_records(tmp_storage_dir, sample_text_files):
    """Test that build_table_from_text creates database records."""
    # Arrange
    subdomain = "test.civic.band"
    db = sqlite_utils.Database(":memory:")
    db["minutes"].create({"id": str, "text": str, ...}, pk="id")

    # Act
    build_table_from_text(subdomain, sample_text_files["minutes_dir"], db, "minutes")

    # Assert
    records = list(db["minutes"].rows)
    assert len(records) == 2
    assert "meeting" in records[0]["text"]
```

### Integration Tests

Integration tests test complete workflows with real databases and files:

```python
import pytest
from click.testing import CliRunner
from clerk.cli import cli

@pytest.mark.integration
def test_full_pipeline(tmp_path, tmp_storage_dir, monkeypatch):
    """Test complete pipeline from create to deploy."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STORAGE_DIR", str(tmp_storage_dir))

    # Create civic.db
    db = sqlite_utils.Database("civic.db")
    db["sites"].insert({...}, pk="subdomain")

    # Run build command
    runner = CliRunner()
    result = runner.invoke(cli, ["build-db-from-text", "-s", "test.civic.band"])

    # Verify results
    assert result.exit_code == 0
    assert Path(tmp_storage_dir / "test.civic.band" / "meetings.db").exists()
```

## Available Fixtures

### Database Fixtures

**sample_db** - Pre-populated civic.db with test sites:

```python
def test_with_sample_db(sample_db):
    """Test using sample civic.db."""
    site = sample_db["sites"].get("example.civic.band")
    assert site["name"] == "Example City Council"
```

**sample_site_db** - Per-site meetings.db with minutes and agendas:

```python
def test_with_site_db(sample_site_db):
    """Test with per-site database."""
    minutes = list(sample_site_db["minutes"].rows)
    assert len(minutes) == 2
```

### File System Fixtures

**tmp_storage_dir** - Temporary STORAGE_DIR:

```python
def test_with_storage(tmp_storage_dir):
    """Test with temporary storage directory."""
    site_dir = tmp_storage_dir / "test.civic.band"
    site_dir.mkdir()
    # ... use site_dir ...
```

**sample_text_files** - Pre-created text files:

```python
def test_with_text_files(sample_text_files):
    """Test with sample text files."""
    minutes_dir = sample_text_files["minutes_dir"]
    agendas_dir = sample_text_files["agendas_dir"]
    # ... process files ...
```

### Mock Fixtures

**mock_fetcher** - Mock fetcher instance:

```python
def test_with_mock_fetcher(mock_fetcher):
    """Test with mock fetcher."""
    mock_fetcher.fetch_events()
    assert mock_fetcher.events_fetched
```

**mock_plugin_manager** - Plugin manager with test plugins:

```python
def test_with_plugins(mock_plugin_manager):
    """Test with plugin manager."""
    result = mock_plugin_manager.hook.fetcher_class(label="test_scraper")
    assert result is not None
```

### Environment Fixtures

**monkeypatch_storage_dir** - Sets STORAGE_DIR environment variable:

```python
def test_with_storage_dir(monkeypatch_storage_dir):
    """Test with STORAGE_DIR set."""
    from clerk.cli import STORAGE_DIR
    assert STORAGE_DIR == str(monkeypatch_storage_dir)
```

**disable_logfire** (autouse) - Disables Logfire for tests:

This fixture runs automatically and mocks Logfire to avoid authentication requirements during tests.

## Mock Objects

### MockFetcher

Basic mock fetcher for testing:

```python
from tests.mocks.mock_fetchers import MockFetcher

fetcher = MockFetcher(site, start_year=2020, all_agendas=False)
fetcher.fetch_events()
assert fetcher.events_fetched
```

### FailingFetcher

Mock fetcher that raises errors:

```python
from tests.mocks.mock_fetchers import FailingFetcher

fetcher = FailingFetcher(site, 2020, False)
with pytest.raises(RuntimeError):
    fetcher.fetch_events()
```

### SlowFetcher

Mock fetcher with configurable delays for performance testing:

```python
from tests.mocks.mock_fetchers import SlowFetcher

fetcher = SlowFetcher(site, 2020, False, delay=0.5)
fetcher.fetch_events()  # Takes 0.5 seconds
```

### FilesystemFetcher

Mock fetcher that creates actual files:

```python
from tests.mocks.mock_fetchers import FilesystemFetcher

fetcher = FilesystemFetcher(site, 2020, True, storage_dir=tmp_storage_dir)
fetcher.fetch_events()
# Creates actual text files in tmp_storage_dir
```

### TestPlugin

Mock plugin with all hooks implemented:

```python
from tests.mocks.mock_plugins import TestPlugin

plugin = TestPlugin()
pm.register(plugin)

# Plugin tracks calls
pm.hook.deploy_municipality(subdomain="test.civic.band")
assert "test.civic.band" in plugin.deployed_subdomains
```

## Testing Patterns

### Testing CLI Commands

Use Click's test runner:

```python
from click.testing import CliRunner
from clerk.cli import cli

def test_cli_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["new"], input="test\nTest City\nCA\n...")

    assert result.exit_code == 0
    assert "created" in result.output
```

### Testing with Temporary Directories

Use tmp_path fixture:

```python
def test_with_temp_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    # Create files in tmp_path
    (tmp_path / "test.txt").write_text("content")

    # Run your code
    # tmp_path is automatically cleaned up
```

### Testing Database Operations

Use in-memory databases for speed:

```python
def test_database_operation():
    db = sqlite_utils.Database(":memory:")
    db["sites"].insert({...})

    # Test operations on db
    assert db["sites"].count == 1
```

### Testing with Monkeypatch

Replace functions or environment variables:

```python
def test_with_monkeypatch(monkeypatch):
    # Mock environment variable
    monkeypatch.setenv("STORAGE_DIR", "/tmp/test")

    # Mock function
    def mock_fetch():
        return ["data"]

    monkeypatch.setattr("clerk.cli.fetch_function", mock_fetch)
```

### Testing Error Handling

```python
def test_error_handling():
    with pytest.raises(ValueError, match="Invalid subdomain"):
        process_invalid_subdomain("bad@subdomain")
```

## Continuous Integration

Tests run automatically on GitHub Actions:

```yaml
# .github/workflows/test.yml
- name: Run tests
  run: pytest tests/ -v --cov --cov-report=xml
```

Tests run on:
- Python 3.12 and 3.13
- Every push to main
- Every pull request

## Best Practices

### 1. Arrange-Act-Assert

Structure tests clearly:

```python
def test_feature():
    # Arrange - Set up test data
    db = create_test_db()
    data = {"key": "value"}

    # Act - Execute the code being tested
    result = process_data(db, data)

    # Assert - Verify the results
    assert result == expected_value
```

### 2. Test One Thing

Each test should test a single behavior:

```python
# Good
def test_creates_site():
    result = create_site("test")
    assert result is not None

def test_site_has_correct_name():
    site = create_site("test")
    assert site["name"] == "test"

# Avoid
def test_site_creation_and_validation_and_deployment():
    # Too many responsibilities
```

### 3. Use Descriptive Names

```python
# Good
def test_fetch_internal_updates_status_to_needs_ocr():
    ...

# Avoid
def test_fetch():
    ...
```

### 4. Isolate Tests

Each test should be independent:

```python
# Good - Uses fixtures for clean state
def test_one(tmp_path):
    db = create_db(tmp_path)
    # ... test ...

def test_two(tmp_path):
    db = create_db(tmp_path)
    # ... test ...
```

### 5. Test Edge Cases

```python
def test_handles_empty_database():
    db = sqlite_utils.Database(":memory:")
    result = process_empty_db(db)
    assert result == []

def test_handles_missing_fields():
    site = {"subdomain": "test"}  # Missing required fields
    with pytest.raises(KeyError):
        validate_site(site)
```

## Debugging Tests

### Run with Verbose Output

```bash
pytest -vv
```

### Show Print Statements

```bash
pytest -s
```

### Drop into Debugger on Failure

```bash
pytest --pdb
```

### Run Last Failed Tests

```bash
pytest --lf
```

### Profile Slow Tests

```bash
pytest --durations=10
```

## Code Coverage Goals

- **Overall**: >80% coverage
- **Core modules** (cli.py, utils.py): >90% coverage
- **New features**: 100% coverage

Check coverage:

```bash
pytest --cov --cov-report=term-missing
```
