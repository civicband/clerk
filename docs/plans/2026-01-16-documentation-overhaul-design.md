# Documentation Overhaul Design

**Date:** 2026-01-16
**Status:** Design
**Goal:** Restructure documentation to eliminate inconsistencies and provide clear paths for setup, operations, and API reference across platforms.

## Problem

Recent feature iterations (task queue system, worker architecture, distributed processing, structured logging) have created documentation debt:

1. **Scattered information:** Same topics covered in README, getting-started, and user-guide with conflicting details
2. **Missing critical content:** Worker setup and distributed deployment not well documented
3. **Outdated workflows:** Commands and procedures have changed but docs lag behind
4. **No clear user journeys:** Hard to find "how do I set up on Linux?" or "how do I add more workers?"

## Target Audiences

**Primary:**
1. **New users** - Setting up Clerk for the first time
2. **Operators** - Running Clerk in production, day-to-day maintenance

**Secondary:**
3. **Contributors** - Extending Clerk with plugins or contributing code

## Design Principles

1. **Single Source of Truth:** Each topic lives in exactly one authoritative location
2. **Task-Oriented:** Organize around real-world tasks users need to accomplish
3. **Progressive Disclosure:** Start simple (single-machine), then show advanced (distributed)
4. **Platform-Specific:** Separate macOS and Linux guides rather than conditionals
5. **Task Completion:** Every guide ends with verification steps

## New Documentation Structure

```
docs/
├── index.md                    # Landing page with quick navigation
├── setup/                      # Complete platform setup guides
│   ├── index.md                # Setup overview + platform chooser
│   ├── prerequisites.md        # System requirements, Redis, PostgreSQL
│   ├── macos.md                # Complete macOS setup
│   ├── linux.md                # Complete Linux setup
│   ├── single-machine.md       # Single-machine worker configuration
│   ├── distributed.md          # Multi-machine worker scaling
│   ├── verification.md         # How to verify setup works
│   └── troubleshooting.md      # Common setup issues
├── operations/                 # Day-to-day maintenance & monitoring
│   ├── index.md                # Operations overview
│   ├── daily-tasks.md          # Common daily operations
│   ├── monitoring.md           # Health checks, metrics, logs
│   ├── troubleshooting.md      # Common issues and fixes
│   ├── scaling.md              # Adding workers, horizontal scaling
│   ├── updates.md              # Upgrading clerk, migrations
│   ├── backup-recovery.md      # Database backups, disaster recovery
│   └── performance-tuning.md   # Optimization tips
├── reference/                  # Complete API documentation
│   ├── index.md                # API reference overview
│   ├── cli/                    # Command-line interface reference
│   │   ├── index.md            # CLI overview
│   │   ├── site-management.md  # new, update, enqueue
│   │   ├── data-pipeline.md    # build-db-from-text, extract-entities
│   │   ├── workers.md          # worker, install-workers, uninstall-workers
│   │   ├── monitoring.md       # status, diagnose-workers
│   │   ├── queue-management.md # enqueue, purge, purge-queue
│   │   └── database.md         # db upgrade, build-full-db
│   ├── python-api/             # Python library reference
│   │   ├── index.md            # Python API overview
│   │   ├── fetcher.md          # Fetcher base class
│   │   ├── db.md               # Database functions
│   │   ├── utils.md            # Utility functions
│   │   ├── workers.md          # Worker job functions
│   │   ├── queue.md            # Queue management
│   │   └── extraction.md       # Entity/vote extraction
│   └── plugin-api/             # Plugin development reference
│       ├── index.md            # Plugin system overview
│       ├── hooks.md            # All available hooks
│       ├── fetcher-plugins.md  # Creating fetcher plugins
│       ├── deployment-plugins.md # Creating deployment plugins
│       └── examples.md         # Real plugin examples
├── guides/                     # Deep-dive tutorials
│   ├── index.md                # Guides overview
│   ├── first-site.md           # Tutorial: Your first site end-to-end
│   ├── worker-architecture.md  # Understanding the task queue system
│   ├── ocr-backends.md         # Choosing and configuring OCR backends
│   ├── extraction-workflow.md  # Entity and vote extraction deep-dive
│   ├── custom-fetcher.md       # Building a custom fetcher plugin
│   ├── custom-deployment.md    # Building a deployment plugin
│   ├── distributed-setup.md    # Real-world distributed deployment
│   ├── production-checklist.md # Pre-production checklist
│   └── migration-guides.md     # Upgrading from older versions
├── architecture/               # System design documentation
│   ├── index.md                # Architecture overview
│   ├── database-schema.md      # civic.db and meetings.db schemas
│   ├── pipeline-flow.md        # Data flow through the system
│   ├── queue-system.md         # RQ architecture and job flow
│   ├── plugin-system.md        # Pluggy integration
│   └── design-decisions.md     # Key architectural choices
├── contributing.md             # Development setup and guidelines
├── design-docs/                # Keep as-is (historical)
└── plans/                      # Keep as-is (historical)
```

## Section Details

### Setup Documentation

**Purpose:** Get users from zero to working Clerk installation with workers running.

**Flow:**
1. **index.md** - Decision tree: Platform? Deployment model?
2. **Platform guides (macos.md, linux.md)** - Install clerk, dependencies, Redis, PostgreSQL
3. **Worker guides (single-machine.md, distributed.md)** - Configure and start workers
4. **verification.md** - Confirm everything works end-to-end

**Key Content:**
- Platform-specific installation (no "if macOS then..." conditionals)
- Environment variable configuration (.env file setup)
- LaunchAgent (macOS) and systemd (Linux) service setup
- Worker architecture explanation (5 queue types)
- Smoke tests and verification procedures

### Operations Documentation

**Purpose:** Day-to-day maintenance for running production Clerk installations.

**Flow:**
1. **daily-tasks.md** - Common operations with one-liners
2. **monitoring.md** - Queue health, worker status, structured logs
3. **troubleshooting.md** - Problem → Diagnosis → Fix format
4. **scaling.md** - Adding workers, distributing load
5. **updates.md** - Safe upgrade procedures
6. **backup-recovery.md** - Data protection
7. **performance-tuning.md** - Optimization

**Key Content:**
- `clerk status` command deep-dive
- Structured logging query examples (filter by subdomain, operation, error)
- Common failure modes and fixes
- When to scale (queue depth indicators)
- Database backup strategies

### Reference Documentation

**Purpose:** Complete API reference for all three interfaces.

**CLI Reference:**
- Every command fully documented
- All flags and options explained
- Usage examples for common cases
- Exit codes and error messages
- Cross-references to related commands

**Python API Reference:**
- Auto-generated from docstrings where possible
- Type signatures and import paths
- Manual examples for complex functions
- Class hierarchies (Fetcher subclasses)

**Plugin API Reference:**
- Complete hook specifications
- Plugin discovery and loading
- Lifecycle documentation
- Testing your plugin
- Real-world examples

### Guides Documentation

**Purpose:** Deep-dive tutorials for advanced topics.

**Key Guides:**
- **first-site.md** - Beginner tutorial from install to deployed site
- **worker-architecture.md** - Understanding task queues and job flow
- **ocr-backends.md** - Tesseract vs Vision Framework comparison
- **extraction-workflow.md** - Entity/vote extraction internals
- **custom-fetcher.md** - Complete plugin development walkthrough
- **distributed-setup.md** - Production deployment example
- **production-checklist.md** - Pre-launch validation

### Architecture Documentation

**Purpose:** System design for contributors and advanced users.

**Content:**
- Database schemas (civic.db, meetings.db)
- Data flow diagrams
- Queue coordination patterns (fan-out/fan-in)
- Plugin loading mechanism
- Design tradeoffs and rationale
- Links to historical design documents

## Migration Plan

### What Gets Retired

**getting-started/** → Merged into **setup/** and **guides/**
- `installation.md` → Split between `setup/macos.md` and `setup/linux.md`
- `quickstart.md` → Becomes `guides/first-site.md` (expanded)
- `basic-usage.md` → Split between `operations/daily-tasks.md` and `guides/first-site.md`

**user-guide/** → Split between **operations/** and **guides/**
- `task-queue.md` → Split into `operations/monitoring.md`, `guides/worker-architecture.md`, `setup/single-machine.md`
- `troubleshooting-workers.md` → Becomes `operations/troubleshooting.md` (expanded)

**developer-guide/** → Multiple destinations
- `architecture.md` → `architecture/` (split into multiple files)
- `plugin-development.md` → `reference/plugin-api/` + `guides/custom-fetcher.md` + `guides/custom-deployment.md`
- `ocr-logging.md` → `architecture/pipeline-flow.md` (section)
- `testing.md` → `contributing.md` (section)
- `DEVELOPMENT.md` → `contributing.md`

**api/** → Enhanced to **reference/**
- Current stubs become full references
- Add `cli/` subdirectory with comprehensive CLI docs
- Add `python-api/` subdirectory with enhanced API docs
- Expand `plugin-api/` with plugin development docs

**Keep As-Is:**
- `plans/` - Historical design documents
- `design-docs/` - Historical design documents
- Link from `architecture/design-decisions.md`

### README.md Changes

**Current:** ~380 lines with duplicated setup, workflow, and configuration docs

**New:** ~100 lines as a "marketing page"
- Quick feature overview
- Installation one-liner: `pip install clerk[pdf,extraction]`
- Platform-specific setup links
- Links to operations and API reference
- Remove all duplicated content

**Example New README Structure:**
```markdown
# clerk

A Python library for managing civic data pipelines...

## Quick Install

pip install clerk[pdf,extraction]

## Documentation

- **Setup:** [macOS](docs/setup/macos.md) | [Linux](docs/setup/linux.md)
- **Operations:** [Daily Tasks](docs/operations/) | [Monitoring](docs/operations/monitoring.md)
- **Reference:** [CLI](docs/reference/cli/) | [Python API](docs/reference/python-api/) | [Plugins](docs/reference/plugin-api/)

## Quick Start

See [Your First Site](docs/guides/first-site.md) for a complete tutorial.

[License, Links, etc.]
```

### contributing.md Structure

**New file consolidating development docs:**

```markdown
# Contributing to Clerk

## Development Setup
- Clone and install with uv
- Running tests (unit, integration)
- Code quality tools (ruff, pytest)

## Testing Guidelines
- Unit vs integration tests
- Writing new tests
- Test coverage expectations
- Testing plugins

## Documentation
- How to update docs
- Building docs locally (Sphinx)
- Documentation standards

## Pull Request Process
- Branch naming conventions
- Commit message format
- Review process
- CI checks
```

## Implementation Approach

**Phase 1: Setup Documentation**
1. Create `setup/` directory structure
2. Write platform-specific guides (macos.md, linux.md)
3. Write worker configuration guides (single-machine.md, distributed.md)
4. Write verification.md
5. Update README.md to link to new setup docs

**Phase 2: Operations Documentation**
1. Create `operations/` directory structure
2. Migrate and expand troubleshooting-workers.md
3. Write monitoring.md (structured logging queries)
4. Write daily-tasks.md, scaling.md, updates.md
5. Write backup-recovery.md, performance-tuning.md

**Phase 3: Reference Documentation**
1. Create `reference/` directory structure
2. Write comprehensive CLI reference
3. Enhance Python API docs (auto-generate + examples)
4. Write complete plugin API reference
5. Retire old api/ stubs

**Phase 4: Guides Documentation**
1. Create `guides/` directory structure
2. Write first-site.md (complete tutorial)
3. Write worker-architecture.md
4. Write custom-fetcher.md and custom-deployment.md
5. Write distributed-setup.md, production-checklist.md

**Phase 5: Architecture & Cleanup**
1. Create `architecture/` directory
2. Split architecture.md into focused files
3. Write contributing.md
4. Update index.md with new structure
5. Archive old directories (getting-started/, user-guide/, developer-guide/)

**Phase 6: Review & Polish**
1. Cross-reference audit (all internal links work)
2. Consistency pass (terminology, formatting)
3. Build and test Sphinx output
4. User testing with fresh install

## Success Criteria

1. **No duplication:** Each topic covered exactly once
2. **Complete journeys:** User can complete setup → operations without external resources
3. **Platform coverage:** macOS and Linux both fully documented
4. **API completeness:** All CLI commands, Python functions, and plugin hooks documented
5. **Verification steps:** Every guide ends with "how to confirm this worked"
6. **Link integrity:** All internal cross-references work

## Out of Scope

- Video tutorials
- Translations
- Interactive documentation
- API changelog (historical changes)
- Performance benchmarks (leave in design docs)

## Open Questions

None - design is complete and approved.

## Next Steps

After design approval:
1. Use `superpowers:using-git-worktrees` to create isolated workspace
2. Use `superpowers:writing-plans` to create detailed implementation plan
3. Execute in phases with review checkpoints
