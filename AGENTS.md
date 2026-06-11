# AGENTS.md — clerk / civicband-clerk

## Package identity
- **PyPI name:** `civicband-clerk`  
- **Import name:** `clerk` (from `src/clerk/`) — these differ on purpose
- **CLI entry point:** `clerk` (set in `[project.scripts]` → `clerk = "clerk:main"`)
- **Version source:** single source of truth at `src/clerk/__init__.py:23` (hatch reads it via `[tool.hatch.version] path`)
- **Build system:** hatchling

## Commands
```
just test           # uv run python -m pytest tests/
just test-v         # verbose
just test-unit      # -m unit
just test-integration  # -m integration
just lint           # ruff check src/ tests/
just lint-fix       # ruff check --fix
just format-check   # ruff format --check
just format         # ruff format
just typecheck      # mypy src/clerk
just check          # lint + format-check + typecheck
just install        # uv pip install -e ".[dev]"
pre-commit run --all-files  # hooks: trailing-whitespace, ruff, mypy
```

## Test quirks
- Coverage is **always on** (configured in `[tool.pytest.ini_options] addopts`)
- Markers: `unit`, `integration`, `slow` — only `unit` is fast; `slow` tests use real IO
- `cli_module` fixture needed: `import clerk.cli` returns the Click group (not the `.py` module). Use `sys.modules["clerk.cli"]` via the fixture to get the actual module.
- `monkeypatch_storage_dir` fixture patches both `clerk.cli.STORAGE_DIR` and `clerk.utils.STORAGE_DIR`
- Integration tests require PostgreSQL+Redis (marked `integration`)
- 224 tests, 3 skipped (PostgreSQL backend tests skipped without `DATABASE_URL`)

## Architecture
- **`src/clerk/cli.py`** — Click CLI, loads `.env` via python-dotenv at import time (**before** any local imports)
- **`src/clerk/workers.py`** — RQ job functions (fetcher sends jobs to queues; workers call these)
- **`src/clerk/fetcher.py`** — `Fetcher` base class + `get_fetcher()` dispatcher
- **`src/clerk/plugin_loader.py`** — pluggy-based plugin system via `civicband.clerk` hookspec namespace
- **`src/clerk/db.py`** — SQLAlchemy + SQLite conn management; alembic migrations in `alembic/`
- **`src/clerk/queue.py`** — RQ queue helpers; 5 worker types: fetch, ocr, compilation, extraction, deploy
- Plugin entry points: `clerk.plugins` group; hookimpl namespace: `civicband.clerk`
- Shared data at install time: `deployment/`, `scripts/`, `alembic.ini`, `alembic/` → `share/clerk/`
- `.env` required at runtime (template at `.env.example`)

## Release flow
- Manual `workflow_dispatch` in GitHub Actions (bump: patch/minor/major)
- Version tagged `vX.Y.Z` and pushed to PyPI automatically
- To release locally: bump `__version__` in `__init__.py`, then `python -m build && twine upload dist/*`
