# Synchronous Pipeline Test Mode

**Date:** 2026-01-17
**Status:** Design
**Priority:** High - Would have caught PR #65 bugs before production

## Problem

The queue-based pipeline is complex and distributed, making it hard to:
- Test the full pipeline locally without Redis infrastructure
- Verify all hooks are called in the correct order
- Debug failures (async logs scattered across workers)
- Catch missing steps before deployment (like the 3 bugs in PR #65)

## Solution

Add `clerk test-pipeline` command that runs the entire pipeline **synchronously** for a single site, calling worker functions directly without Redis/RQ.

## Implementation

```python
# Add to cli.py

@cli.command()
@click.argument("subdomain")
@click.option("--all-years", is_flag=True, help="Fetch all years, not just recent")
@click.option("--all-agendas", is_flag=True, help="Fetch both agendas and minutes")
@click.option("--skip-fetch", is_flag=True, help="Skip fetch, start from OCR")
@click.option("--skip-ocr", is_flag=True, help="Skip OCR, start from compilation")
@click.option("--extract-entities/--no-extract-entities", default=True)
@click.option("--ocr-backend", default="tesseract", type=click.Choice(["tesseract", "vision"]))
@click.option("--dry-run", is_flag=True, help="Show what would run without executing")
def test_pipeline(subdomain, all_years, all_agendas, skip_fetch, skip_ocr, extract_entities, ocr_backend, dry_run):
    """Run full pipeline synchronously for testing (no Redis required)."""

    import time
    from pathlib import Path

    run_id = f"test_{subdomain}_{int(time.time())}"

    click.echo(f"🧪 Testing pipeline for {subdomain} (run_id: {run_id})")
    click.echo(f"Mode: {'DRY RUN' if dry_run else 'EXECUTE'}\n")

    # Track what gets called
    hooks_called = []

    def log_hook(hook_name, **kwargs):
        hooks_called.append(hook_name)
        click.echo(f"  ✓ {hook_name}({', '.join(f'{k}={v}' for k, v in kwargs.items())})")

    # Phase 1: Fetch
    if not skip_fetch:
        click.echo("📥 Phase 1: Fetch")
        if not dry_run:
            from clerk.workers import fetch_site_job
            from clerk.db import civic_db_connection, get_site_by_subdomain

            with civic_db_connection() as conn:
                site = get_site_by_subdomain(conn, subdomain)

            fetch_site_job(subdomain, run_id=run_id, all_years=all_years, all_agendas=all_agendas)
            log_hook("fetch_site_job", subdomain=subdomain)
        else:
            click.echo("  [Would call fetch_site_job]")

    # Phase 2: OCR (collect all PDFs, run OCR jobs synchronously)
    if not skip_ocr:
        click.echo("\n🔍 Phase 2: OCR")
        storage_dir = os.getenv("STORAGE_DIR", "../sites")
        pdf_dir = Path(f"{storage_dir}/{subdomain}/pdfs")

        if pdf_dir.exists():
            pdf_files = list(pdf_dir.glob("**/*.pdf"))
            click.echo(f"  Found {len(pdf_files)} PDFs to OCR")

            if not dry_run:
                from clerk.workers import ocr_page_job

                for i, pdf_path in enumerate(pdf_files, 1):
                    click.echo(f"  [{i}/{len(pdf_files)}] {pdf_path.name}...", nl=False)
                    try:
                        ocr_page_job(subdomain, str(pdf_path), backend=ocr_backend, run_id=run_id)
                        click.echo(" ✓")
                    except Exception as e:
                        click.echo(f" ✗ {e}")

                log_hook("ocr_page_job", count=len(pdf_files))
        else:
            click.echo(f"  ⚠ No PDFs found at {pdf_dir}")

    # Phase 3: Coordinator (marks OCR complete)
    click.echo("\n⚙️  Phase 3: OCR Coordinator")
    if not dry_run:
        from clerk.workers import ocr_complete_coordinator
        ocr_complete_coordinator(subdomain, run_id=run_id)
        log_hook("ocr_complete_coordinator", subdomain=subdomain)
    else:
        click.echo("  [Would call ocr_complete_coordinator]")

    # Phase 4: Compilation (two paths in parallel normally, sequential here)
    click.echo("\n🗄️  Phase 4: Database Compilation")

    # Path 1: No entities (fast)
    click.echo("  Path 1: Without entities")
    if not dry_run:
        from clerk.workers import db_compilation_job
        db_compilation_job(subdomain, run_id=run_id, extract_entities=False)
        log_hook("db_compilation_job", extract_entities=False)
    else:
        click.echo("    [Would call db_compilation_job(extract_entities=False)]")

    # Path 2: With entities (if enabled)
    if extract_entities:
        click.echo("  Path 2: With entity extraction")
        if not dry_run:
            from clerk.workers import extraction_job, db_compilation_job
            extraction_job(subdomain, run_id=run_id)
            log_hook("extraction_job", subdomain=subdomain)

            db_compilation_job(subdomain, run_id=run_id, extract_entities=True)
            log_hook("db_compilation_job", extract_entities=True)
        else:
            click.echo("    [Would call extraction_job + db_compilation_job(extract_entities=True)]")

    # Phase 5: Deploy
    click.echo("\n🚀 Phase 5: Deploy")
    if not dry_run:
        from clerk.workers import deploy_job
        deploy_job(subdomain, run_id=run_id)
        log_hook("deploy_job", subdomain=subdomain)
    else:
        click.echo("  [Would call deploy_job]")

    # Summary
    click.echo("\n" + "="*60)
    click.echo("📊 Pipeline Summary")
    click.echo("="*60)
    click.echo(f"\nHooks called ({len(hooks_called)}):")
    for hook in hooks_called:
        click.echo(f"  ✓ {hook}")

    # Verification against expected hooks
    expected_hooks = [
        "fetch_site_job",
        "ocr_page_job",
        "ocr_complete_coordinator",
        "db_compilation_job",  # x2 if extract_entities
        "deploy_job",
    ]

    if extract_entities:
        expected_hooks.insert(-1, "extraction_job")

    click.echo(f"\nExpected: {len(expected_hooks)} hook types")
    click.echo(f"Called: {len(set(hooks_called))} unique hook types")

    missing = set(expected_hooks) - set(hooks_called)
    if missing:
        click.echo(f"\n⚠️  WARNING: Missing hooks!")
        for hook in missing:
            click.echo(f"  ✗ {hook}")
        sys.exit(1)
    else:
        click.echo(f"\n✅ All expected hooks called!")
```

## Usage Examples

```bash
# Test full pipeline locally (no Redis needed)
clerk test-pipeline alameda

# Dry run to see what would execute
clerk test-pipeline alameda --dry-run

# Skip stages for faster iteration
clerk test-pipeline alameda --skip-fetch          # Already have PDFs
clerk test-pipeline alameda --skip-fetch --skip-ocr  # Already have text files

# Test without entity extraction (faster)
clerk test-pipeline alameda --no-extract-entities

# Test with Vision OCR
clerk test-pipeline alameda --ocr-backend vision
```

## Benefits

1. **Catches missing hooks** - Would have caught all 3 bugs in PR #65:
   - Missing `update_page_count()`
   - Missing `post_deploy()` hook
   - Missing `rebuild_site_fts_internal()`

2. **No infrastructure required** - Works without:
   - Redis/RQ setup
   - Background workers
   - Distributed queue system

3. **Fast debugging**
   - Full stack traces immediately visible
   - No async complexity
   - Step through with debugger
   - Clear execution order

4. **CI-friendly**
   - Can run in GitHub Actions
   - Deterministic (no race conditions)
   - Fast feedback on PRs

5. **Documentation**
   - Shows expected flow
   - Self-documenting pipeline
   - Onboarding tool for new developers

## Validation Features

### Hook Call Verification

The command tracks all hooks called and compares against expected hooks:

```
📊 Pipeline Summary
==================
Hooks called (6):
  ✓ fetch_site_job
  ✓ ocr_page_job
  ✓ ocr_complete_coordinator
  ✓ db_compilation_job
  ✓ extraction_job
  ✓ deploy_job

Expected: 6 hook types
Called: 6 unique hook types

✅ All expected hooks called!
```

If hooks are missing:

```
⚠️  WARNING: Missing hooks!
  ✗ update_page_count
  ✗ post_deploy
  ✗ rebuild_site_fts_internal
```

## Future Enhancements

### 1. Comparison Mode

Compare synchronous execution against production behavior:

```bash
clerk test-pipeline alameda --compare-with-production
```

Would show:
```
Comparing against production deployment flow...

✅ Status updates: MATCH
✅ Page count update: MATCH
✅ post_deploy hook: MATCH
✅ FTS rebuild: MATCH
❌ Hook order: MISMATCH
   Expected: fetch → ocr → compile → deploy
   Got: fetch → compile → ocr → deploy
```

### 2. Performance Profiling

```bash
clerk test-pipeline alameda --profile
```

Output:
```
Phase Timing:
  Fetch: 12.3s
  OCR: 145.7s (avg 2.1s/page, 70 pages)
  Compilation: 8.4s
  Deploy: 2.1s

Total: 168.5s

Slowest operations:
  1. OCR page 42 (vision): 15.2s
  2. OCR page 15 (vision): 12.8s
  3. Entity extraction: 7.3s
```

### 3. Snapshot Testing

Generate snapshots of database/filesystem state at each phase:

```bash
clerk test-pipeline alameda --snapshot
```

Creates:
```
snapshots/alameda_1234567890/
  ├─ 1_after_fetch.json
  ├─ 2_after_ocr.json
  ├─ 3_after_compilation.json
  └─ 4_after_deploy.json
```

Then compare:
```bash
clerk test-pipeline alameda --compare-snapshot snapshots/alameda_1234567890/
```

### 4. Chaos Testing

Inject failures at various stages:

```bash
clerk test-pipeline alameda --fail-at ocr --retry
```

Test resilience and retry logic.

## Implementation Priority

**Phase 1 (MVP):**
- Basic synchronous execution
- Hook tracking
- Dry-run mode
- Skip flags for faster iteration

**Phase 2 (Validation):**
- Expected hooks verification
- Exit code on missing hooks
- Summary report

**Phase 3 (Advanced):**
- Comparison mode
- Performance profiling
- Snapshot testing

## How This Would Have Prevented PR #65 Issues

If we had this command, during development:

```bash
$ clerk test-pipeline alameda --dry-run

📥 Phase 1: Fetch
  [Would call fetch_site_job]

🔍 Phase 2: OCR
  [Would call ocr_page_job for 70 PDFs]

⚙️  Phase 3: OCR Coordinator
  [Would call ocr_complete_coordinator]

🗄️  Phase 4: Database Compilation
  [Would call db_compilation_job]

🚀 Phase 5: Deploy
  [Would call deploy_job]

📊 Pipeline Summary
==================
Expected hooks:
  ✓ fetch_site_job
  ✓ ocr_page_job
  ✓ ocr_complete_coordinator
  ✓ db_compilation_job
  ✓ deploy_job

⚠️  WARNING: Missing hooks!
  ✗ update_page_count
  ✗ post_deploy
  ✗ rebuild_site_fts_internal

❌ Test failed: 3 expected hooks not called
```

Developer would immediately know something was wrong!

## Related Work

- Old `clerk update` command (synchronous, but couldn't test queue workers)
- Queue worker pipeline (distributed, hard to test locally)
- This bridges both: test queue workers synchronously

## Questions to Answer

1. Should this replace `clerk update` entirely?
2. How to handle hooks that need external services (SSH, etc)?
3. Should we mock external dependencies for testing?
4. Integration with pytest for automated testing?
