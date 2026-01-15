# Auto-Enqueue Scheduler Design

**Date**: 2026-01-14
**Status**: Approved
**Authors**: Claude Sonnet 4.5, phildini

## Executive Summary

This design adds automatic site scheduling to the RQ-based task queue system. A simple cron job runs every minute to enqueue the least-recently-updated site, ensuring all sites update approximately once per day while allowing manual priority overrides.

**Key Benefits:**
- **Even distribution** - Sites naturally spread across 24 hours based on last update time
- **Simple implementation** - ~30 lines of code, reuses existing enqueue infrastructure
- **Manual overrides** - High-priority queue for urgent manual updates
- **Self-healing** - Missed cron runs automatically catch up
- **No new infrastructure** - Standard cron, no new dependencies

## Motivation

The new RQ worker architecture enables parallel processing but requires a scheduling mechanism to automatically feed sites into the queue. Previously, `clerk update -n` was called via launchd every 15 minutes to process one site synchronously. Now we need to enqueue sites at a regular cadence for workers to process.

**Requirements:**
1. All sites update approximately once per day
2. Manual updates can jump to front of queue
3. New sites are prioritized for immediate processing
4. Simple, minimal infrastructure
5. Reuses existing queue and enqueue mechanisms

## Design

### Command Behavior

**1. `clerk new <subdomain>` - Create new site**
- Creates site record in database (existing behavior)
- Enqueues site with **high priority**
- New sites process immediately

**2. `clerk update -s <subdomain>` - Manual update**
- Enqueues specific site with **high priority**
- Replaces old synchronous processing with async enqueue
- Jumps to front of queue

**3. `clerk update --next` - Auto-scheduler**
- Finds site with oldest `last_updated` timestamp
- Skips sites updated within last 23 hours
- Enqueues with **normal priority**
- Called by cron every minute

**4. `clerk enqueue <subdomain>...` - Bulk enqueue**
- Enqueues with **normal priority** by default
- User can override: `--priority high`
- Used for bulk operations

### Priority Queue Model

Two priority levels:
- **High priority**: Manual `new` and `update` commands - process first
- **Normal priority**: Auto-scheduler and bulk enqueues - process after high queue empty

RQ processes high-priority jobs before normal-priority jobs automatically.

### Scheduling Algorithm

**Query Logic** (SQLAlchemy):
```python
def get_oldest_site(lookback_hours=23):
    """Find site with oldest last_updated timestamp.

    Returns None if all sites updated within lookback window.
    """
    from sqlalchemy import select, or_
    from datetime import datetime, timedelta
    from .models import sites_table
    from .db import civic_db_connection

    cutoff = datetime.now() - timedelta(hours=lookback_hours)

    stmt = select(sites_table.c.subdomain).where(
        or_(
            sites_table.c.last_updated.is_(None),
            sites_table.c.last_updated < cutoff
        )
    ).order_by(
        sites_table.c.last_updated.asc().nulls_first()
    ).limit(1)

    with civic_db_connection() as conn:
        result = conn.execute(stmt).fetchone()
        return result[0] if result else None
```

**Properties:**
- Sites with `NULL` last_updated (never processed) get highest priority
- 23-hour lookback ensures ~24-hour update cycle
- If all sites updated recently, returns `None` (nothing to do)
- Self-healing: if scheduler misses runs, oldest sites get caught up first

### Implementation Changes

**`clerk update` command**:
```python
@cli.command()
@click.option('-s', '--subdomain', help='Specific site subdomain')
@click.option('-n', '--next-site', is_flag=True, help='Enqueue oldest site')
@click.option('-a', '--all-years', is_flag=True)
# ... other options
def update(subdomain, next_site, all_years, ...):
    if next_site:
        # Auto-scheduler mode
        subdomain = get_oldest_site(lookback_hours=23)
        if not subdomain:
            click.echo("No sites eligible for auto-enqueue")
            return
        click.echo(f"Auto-enqueueing {subdomain}")
        enqueue_site(subdomain, priority='normal')
        return

    if subdomain:
        # Manual update mode
        click.echo(f"Enqueueing {subdomain} with high priority")
        enqueue_site(subdomain, priority='high', all_years=all_years, ...)
        return

    # Error: must specify --subdomain or --next-site
    raise click.UsageError("Must specify --subdomain or --next-site")
```

**`clerk new` command**:
```python
@cli.command()
@click.argument('subdomain')
# ... other options
def new(subdomain, ...):
    # Create site in database (existing logic)
    create_site_record(subdomain, ...)

    # Auto-enqueue at high priority
    click.echo(f"Enqueueing new site {subdomain} with high priority")
    enqueue_site(subdomain, priority='high')
```

**`clerk enqueue` command** (no changes):
```python
# Already uses priority='normal' by default
# Already supports --priority option for overrides
```

### Error Handling

**No eligible sites**:
```python
# All sites updated within 23 hours
subdomain = get_oldest_site(lookback_hours=23)
if not subdomain:
    # Exit successfully - nothing to do
    return
```

**Site already in queue**:
- RQ handles naturally - multiple jobs for same site is fine
- Workers are idempotent
- `site_progress` tracks current stage
- No special handling needed

**Database/Redis connection failures**:
- Let exceptions propagate
- Cron retries next minute automatically
- Errors logged to cron output

### Deployment

**Cron Configuration**:
```bash
# Add to crontab: crontab -e
* * * * * cd /path/to/project && /path/to/uv run clerk update --next >> /var/log/clerk/auto-enqueue.log 2>&1
```

**Monitoring**:
- Check `/var/log/clerk/auto-enqueue.log` to see enqueued sites
- Use `clerk status` to see queue depths
- Use RQ dashboard for detailed queue monitoring

**No database migration needed** - Uses existing `sites.last_updated` column.

## Example Scenarios

**Typical day**:
```bash
00:00 - Cron enqueues site-a (last_updated: 2026-01-12 23:58)
00:01 - Cron enqueues site-b (last_updated: 2026-01-12 23:59)
00:02 - Cron enqueues site-c (last_updated: 2026-01-13 00:00)
...
```

**Manual override**:
```bash
10:30 - User runs: clerk update -s important-city
        → important-city added to high-priority queue
        → Workers process high-priority queue first
        → important-city completes, last_updated set to 10:35
        → Auto-scheduler won't pick important-city until tomorrow
```

**New site**:
```bash
14:00 - User runs: clerk new brand-new-city
        → Site created in database (last_updated = NULL)
        → Enqueued with high priority
        → Processes immediately
        → last_updated set when complete
```

**All sites recently updated**:
```bash
03:00 - All sites updated within last 23 hours
        → get_oldest_site() returns None
        → Cron run exits successfully
        → No unnecessary work
```

## Trade-offs

**Pros:**
- Extremely simple implementation
- Reuses all existing infrastructure
- Natural load distribution
- Manual overrides work intuitively
- Self-healing on missed runs

**Cons:**
- Fixed 1 site/minute rate (could add `--batch-size` later if needed)
- Hardcoded 23-hour lookback (could make configurable later)
- Cron log noise if all sites recently updated (minor)

## Future Enhancements

**Not included in this design** (YAGNI - add only if needed):

1. **Configurable cadence** - Some sites update more frequently than others
2. **Batch enqueuing** - Enqueue multiple sites per cron run
3. **Smart scheduling** - Adjust frequency based on site activity
4. **Install commands** - `clerk install-scheduler` automation
5. **Lookback configuration** - Make 23-hour window configurable

All of these can be added later without changing the core design.

## Implementation Checklist

- [ ] Add `get_oldest_site()` helper function
- [ ] Update `clerk update` command to handle `--next-site` flag
- [ ] Update `clerk new` command to auto-enqueue with high priority
- [ ] Update `clerk update -s` to enqueue with high priority instead of processing synchronously
- [ ] Add logging for auto-enqueue operations
- [ ] Update documentation with new command behavior
- [ ] Add cron setup instructions to deployment docs
- [ ] Write tests for `get_oldest_site()` function
- [ ] Write tests for updated command behavior
