# Clerk development tasks

# List available tasks
default:
    @just --list

# Install development dependencies
install:
    uv pip install -e ".[dev]"

# Run all tests
test *args:
    uv run python -m pytest tests/ {{args}}

# Run tests with verbose output
test-v:
    uv run python -m pytest tests/ -v

# Run only unit tests
test-unit:
    uv run python -m pytest tests/ -m unit

# Run only integration tests
test-integration:
    uv run python -m pytest tests/ -m integration

# Run linter
lint:
    uv run ruff check src/ tests/

# Run linter with auto-fix
lint-fix:
    uv run ruff check src/ tests/ --fix

# Check formatting
format-check:
    uv run ruff format --check src/ tests/

# Format code
format:
    uv run ruff format src/ tests/

# Run type checker
typecheck:
    uv run mypy src/clerk

# Run all checks (lint, format, typecheck)
check: lint format-check typecheck

# Run pre-commit hooks
pre-commit:
    uv run pre-commit run --all-files
