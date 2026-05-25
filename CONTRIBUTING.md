# Contributing to Clerk

Thank you for your interest in contributing to Clerk! This document provides guidelines and instructions for contributing.

## Development Setup

### Prerequisites

- Python 3.12 or higher
- Git
- [uv](https://github.com/astral-sh/uv) for dependency management
- [just](https://github.com/casey/just) for running tasks

### Getting Started

1. **Fork and clone the repository:**

```bash
git clone https://github.com/YOUR_USERNAME/clerk.git
cd clerk
```

2. **Install development dependencies:**

```bash
just install
```

3. **Verify installation:**

```bash
just test
```

## Development Workflow

### Making Changes

1. **Create a new branch:**

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/your-bug-fix
```

2. **Make your changes** following the code style guidelines below

3. **Write tests** for your changes:
   - Unit tests in `tests/test_*.py`
   - Integration tests in `tests/test_integration.py`

4. **Run tests locally:**

```bash
# Run all tests
just test

# Run unit tests only
just test-unit

# Run integration tests only
just test-integration

# Run specific test file
just test tests/test_cli.py
```

5. **Format and lint:**

```bash
# Format code
just format

# Check linting
just lint

# Auto-fix linting issues
just lint-fix

# Type check
just typecheck

# Run all checks (lint, format, typecheck)
just check
```

6. **Commit your changes:**

```bash
git add .
git commit -m "Brief description of changes"
```

Pre-commit hooks will automatically run formatting and linting checks.

### Running Standalone Development

Clerk is designed to work standalone without setting up caller repositories:

1. **Use the test fixtures:**

```python
from tests.conftest import sample_db, tmp_storage_dir, mock_fetcher

# In your test or development script
def test_my_feature(tmp_storage_dir, sample_db):
    # Your code here
    pass
```

2. **Use mock plugins:**

```python
from tests.mocks.mock_plugins import TestPlugin
from tests.mocks.mock_fetchers import MockFetcher

# Register test plugins
pm.register(TestPlugin())
```

3. **Use sample data:**

Sample sites, text files, and databases are in `tests/fixtures/`

## Code Style Guidelines

### Python Style

- **Line length**: 100 characters
- **Formatting**: Use Ruff (automatically enforced by pre-commit)
- **Imports**: Sorted by Ruff
- **Type hints**: Encouraged but not required initially
- **Docstrings**: Use for all public functions and classes

### Commit Messages

- Use clear, descriptive commit messages
- Start with a verb (Add, Fix, Update, etc.)
- Keep first line under 72 characters
- Add detail in commit body if needed

Example:
```
Add support for custom fetcher timeout

- Add timeout parameter to fetcher interface
- Update MockFetcher with configurable timeout
- Add tests for timeout behavior
```

### Testing Guidelines

- **Test coverage**: Aim for >80% coverage for new code
- **Test organization**:
  - Unit tests: Test individual functions in isolation
  - Integration tests: Test complete workflows
  - Mark integration tests with `@pytest.mark.integration`

- **Fixtures**: Use pytest fixtures from `conftest.py`
- **Mocking**: Use provided mock classes when possible

Example test:
```python
@pytest.mark.unit
def test_build_table_from_text(tmp_storage_dir, sample_text_files):
    """Test that build_table_from_text creates records correctly."""
    # Arrange
    db = sqlite_utils.Database(":memory:")
    db["minutes"].create(...)

    # Act
    build_table_from_text(...)

    # Assert
    records = list(db["minutes"].rows)
    assert len(records) == 2
```

## Pull Request Process

1. **Ensure all tests pass:**

```bash
just test
```

2. **Update documentation** if needed:
   - README.md for user-facing changes
   - Docstrings for API changes
   - docs/ for architecture changes

3. **Create a pull request:**
   - Provide a clear description of changes
   - Reference any related issues
   - Ensure CI checks pass

4. **Code review:**
   - Address reviewer feedback
   - Keep discussion focused and professional

5. **Merge:**
   - Squash commits if requested
   - Maintainer will merge when ready

## Project Structure

```
clerk/
├── src/clerk/          # Main source code
│   ├── __init__.py     # Package initialization, Logfire setup
│   ├── cli.py          # CLI commands and database operations
│   ├── hookspecs.py    # Plugin hook specifications
│   ├── plugins.py      # Dummy plugin implementations
│   └── utils.py        # Utility functions
├── tests/              # Test suite
│   ├── conftest.py     # Pytest fixtures
│   ├── test_*.py       # Test modules
│   ├── fixtures/       # Sample data
│   └── mocks/          # Mock implementations
├── docs/               # Documentation
├── examples/           # Example code
└── .github/            # CI/CD workflows
```

## Writing Plugins

Plugins extend Clerk's functionality. See [docs/plugin-development.md](docs/plugin-development.md) for details.

Basic plugin example:

```python
from clerk import hookimpl

class MyPlugin:
    @hookimpl
    def fetcher_class(self, label):
        if label == "my_scraper":
            return MyFetcherClass
        return None

    @hookimpl
    def deploy_municipality(self, subdomain):
        # Your deployment logic
        pass
```

## Debugging

### Running Clerk in Development Mode

```python
# In Python REPL or script
import os
os.environ["STORAGE_DIR"] = "/tmp/test_storage"

from clerk.cli import cli
from click.testing import CliRunner

runner = CliRunner()
result = runner.invoke(cli, ["--help"])
print(result.output)
```

### Using Logfire for Debugging

Logfire traces are automatically captured:

```bash
# View traces at https://logfire.pydantic.dev
logfire auth
```

### Common Issues

**Import errors:**
- Ensure you installed with `just install`

**Test failures:**
- Check that `STORAGE_DIR` isn't interfering with tests
- Use `just test-v` for verbose output

**Pre-commit hook failures:**
- Run `just format` and `just lint-fix` manually
- Commit the formatted code

### After Submitting PRs

One of the maintainers will review your PR at our earliest convenience. We might have follow-up questions, which we'll post either as a comment on the PR (for overall/general feedback) or using the GitHub reviews workflow (for line-specific feedback). If we don't get a response to questions about your PR within a month, we'll close the PR to avoid stale PR buildup. You should feel free to reopen it when you come back, though! 

- Be respectful and inclusive
- Focus on constructive feedback
- Help others learn and grow

Thank you for contributing to Clerk! 🎉

## Getting Help

- **Issues**: https://github.com/civicband/clerk/issues
- **Discussions**: https://github.com/civicband/clerk/discussions
- **Documentation**: [docs/](docs/)

## Code of Conduct

We use Civic Band's organization-level [Code of Conduct](https://github.com/civicband/.github/blob/main/CODE_OF_CONDUCT.md).

