"""Command-line interface for clerk.

This module provides the main CLI commands for managing civic data pipelines,
including site creation, data fetching, OCR processing, and database operations.
"""

import atexit
import datetime
import json
import logging
import os
import sys
import time
from sqlite3 import OperationalError

import click
import sqlite_utils
from dotenv import find_dotenv, load_dotenv

from .db import civic_db_connection

# Load .env file BEFORE local imports so extraction.py can read env vars
# Use find_dotenv() to search parent directories for .env file
load_dotenv(find_dotenv())

# ruff: noqa: E402
from datetime import UTC

from . import output
from .db import db
from .debug import debug
from .etl import etl
from .extract_cli import extract
from .fetcher import Fetcher
from .output import log
from .plugin_loader import load_plugins_from_directory, load_plugins_from_entry_points
from .sentry import init_sentry
from .utils import assert_db_exists, pm

# Initialize Sentry for error tracking (if SENTRY_DSN is configured)
init_sentry()

logger = logging.getLogger(__name__)


class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    # Standard LogRecord attributes to exclude from extra fields
    RESERVED_ATTRS = {
        "name",
        "msg",
        "args",
        "created",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "exc_info",
        "exc_text",
        "thread",
        "threadName",
        "taskName",
        "message",
    }

    def format(self, record):
        import json

        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include extra fields passed via extra={}
        for key, value in record.__dict__.items():
            if key not in self.RESERVED_ATTRS and not key.startswith("_"):
                log_record[key] = value

        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)


def configure_logging(command_name: str = "unknown"):
    """Configure logging to push to Loki (if configured) and console."""
    handlers = []

    # Always add console handler for local visibility
    console = logging.StreamHandler()
    console.setFormatter(JsonFormatter())
    handlers.append(console)

    # Add Loki handler if URL is configured
    loki_url = os.environ.get("LOKI_URL")
    if loki_url:
        import logging_loki

        # Use synchronous LokiHandler instead of LokiQueueHandler
        # LokiQueueHandler uses a background thread that doesn't survive RQ worker forks
        loki_handler = logging_loki.LokiHandler(
            url=f"{loki_url}/loki/api/v1/push",
            tags={"job": "clerk", "host": os.uname().nodename, "command": command_name},
            version="1",
        )
        loki_handler.setFormatter(JsonFormatter())
        handlers.append(loki_handler)

    logging.basicConfig(
        level=logging.INFO,
        handlers=handlers,
    )

    # Suppress noisy httpx logs (we log requests ourselves)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # Register atexit handler to flush logs on exit
    def flush_logs_on_exit():
        """Flush all log handlers on exit."""
        sys.stderr.flush()
        sys.stdout.flush()
        for handler in logging.getLogger().handlers:
            handler.flush()

    atexit.register(flush_logs_on_exit)


STORAGE_DIR = os.environ.get("STORAGE_DIR", "../sites")


@click.group()
@click.version_option()
@click.option(
    "--plugins-dir",
    default="./plugins",
    type=click.Path(),
    help="Directory to load plugins from",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Suppress console output (logs still go to Loki)",
)
@click.pass_context
def cli(ctx, plugins_dir, quiet):
    """Managing civic.band sites"""
    configure_logging(ctx.invoked_subcommand or "cli")
    output.configure(quiet=quiet)
    # Load directory-based plugins if specified
    load_plugins_from_directory(plugins_dir)


def _load_entry_point_plugins():
    """Load plugins from entry points and register their commands.

    This is called after module initialization to avoid circular imports.
    """
    load_plugins_from_entry_points()

    # Register plugin CLI commands from entry points
    for plugin_commands in pm.hook.register_cli_commands():
        if plugin_commands:
            # Add the command or group directly to preserve structure
            cli.add_command(plugin_commands)


# Load entry point plugins after the module is fully initialized
# We do this at the end of the module to avoid circular import issues
_load_entry_point_plugins()


def fetch_internal(subdomain: str, fetcher: Fetcher):
    from .db import civic_db_connection, update_site

    logger.info("Starting fetch subdomain=%s", subdomain)
    with civic_db_connection() as conn:
        update_site(
            conn,
            subdomain,
            {
                "status": "fetching",
                "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )
    st = time.time()
    fetcher.fetch_events()
    et = time.time()
    elapsed_time = et - st
    log(
        f"Fetch time: {elapsed_time:.2f} seconds",
        subdomain=subdomain,
        elapsed_time=f"{elapsed_time:.2f}",
    )
    status = "needs_ocr"
    with civic_db_connection() as conn:
        update_site(
            conn,
            subdomain,
            {
                "status": status,
                "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )


def rebuild_site_fts_internal(subdomain):
    log("Rebuilding FTS indexes", subdomain=subdomain)
    site_db = sqlite_utils.Database(f"{STORAGE_DIR}/{subdomain}/meetings.db")
    for table_name in site_db.table_names():
        if table_name.startswith("pages_"):
            site_db[table_name].drop(ignore=True)
    try:
        site_db["agendas"].enable_fts(["text"])
    except OperationalError as e:
        log(str(e), subdomain=subdomain, level="error")
    try:
        site_db["minutes"].enable_fts(["text"])
    except OperationalError as e:
        log(str(e), subdomain=subdomain, level="error")


def update_page_count(subdomain):
    from .db import civic_db_connection, update_site

    assert_db_exists()
    site_db = sqlite_utils.Database(f"{STORAGE_DIR}/{subdomain}/meetings.db")
    agendas_count = site_db["agendas"].count
    minutes_count = site_db["minutes"].count
    page_count = agendas_count + minutes_count
    logger.info(
        "Page count updated subdomain=%s agendas=%d minutes=%d total=%d",
        subdomain,
        agendas_count,
        minutes_count,
        page_count,
    )
    with civic_db_connection() as conn:
        update_site(
            conn,
            subdomain,
            {
                "pages": page_count,
                "last_updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            },
        )


@cli.command()
@click.argument(
    "worker_type", type=click.Choice(["fetch", "ocr", "compilation", "extraction", "deploy"])
)
@click.option("--num-workers", "-n", type=int, default=1, help="Number of workers to start")
@click.option("--burst", is_flag=True, help="Exit when queue empty (for testing)")
def worker(worker_type, num_workers, burst):
    """Start RQ workers."""
    import redis
    from rq import Worker
    from rq.worker_pool import WorkerPool

    class DiagnosticWorker(Worker):
        """Custom RQ Worker with pre-fork diagnostic logging."""

        def perform_job(self, job, queue):
            """Override to add logging before and after fork happens."""
            import sys

            # Log BEFORE forking work-horse (this is in parent process)
            try:
                # Safely convert args to string (handles MagicMock in tests)
                args_str = str(job.args) if job.args else "none"
                args_preview = args_str[:50] if len(args_str) > 50 else args_str
                # Use structured logging for Loki/Grafana visibility
                logger.info(
                    "worker_pre_fork",
                    extra={
                        "stage": "pre_fork",
                        "job_id": job.id,
                        "func_name": job.func_name,
                        "args_preview": args_preview,
                    },
                )
                sys.stderr.flush()
            except Exception:
                pass

            # Call parent implementation (this will fork and execute job)
            result = super().perform_job(job, queue)

            # Log AFTER fork completes (back in parent process)
            try:
                logger.info(
                    "worker_post_fork",
                    extra={
                        "stage": "post_fork",
                        "job_id": job.id,
                    },
                )
                sys.stderr.flush()
            except Exception:
                pass

            return result

    from .queue import (
        get_compilation_queue,
        get_deploy_queue,
        get_extraction_queue,
        get_fetch_queue,
        get_high_queue,
        get_ocr_queue,
        get_redis,
    )

    # Validate Redis connection before starting workers
    try:
        get_redis()
    except (redis.ConnectionError, redis.TimeoutError) as e:
        click.secho(f"Error: Cannot connect to Redis: {e}", fg="red")
        raise click.Abort() from e

    # Map worker types to queue lists (each worker checks high priority first)
    queue_map = {
        "fetch": [get_high_queue(), get_fetch_queue()],
        "ocr": [get_high_queue(), get_ocr_queue()],
        "compilation": [get_high_queue(), get_compilation_queue()],
        "extraction": [get_high_queue(), get_extraction_queue()],
        "deploy": [get_high_queue(), get_deploy_queue()],
    }

    # Default job timeouts per worker type (for jobs without explicit timeout)
    # Note: Individual jobs can override with job_timeout parameter when enqueuing
    timeout_map = {
        "fetch": 3600,  # 1 hour - fetching PDFs from city websites
        "ocr": 3600,  # 1 hour - OCR can be slow, especially with Vision
        "compilation": 3600,  # 1 hour - database compilation with large datasets
        "extraction": 7200,  # 2 hours - LLM-based entity extraction
        "deploy": 600,  # 10 minutes - S3 upload and CDN deployment
    }

    queues = queue_map[worker_type]
    default_timeout = timeout_map[worker_type]

    if num_workers == 0:
        click.secho(f"Not starting workers for {worker_type}")
        return

    if num_workers == 1:
        # Single worker with diagnostic logging
        worker_instance = DiagnosticWorker(
            queues, connection=get_redis(), default_worker_ttl=default_timeout
        )
        worker_instance.work(with_scheduler=True, burst=burst)
    else:
        # Worker pool for multiple workers
        # WorkerPool passes worker_class parameter to use our DiagnosticWorker
        with WorkerPool(
            queues,
            num_workers=num_workers,
            connection=get_redis(),
            default_worker_ttl=default_timeout,
            worker_class=DiagnosticWorker,
        ) as pool:  # type: ignore
            pool.start()


@cli.command()
def install_workers():
    """Install RQ workers as background services (macOS/Linux)."""
    import subprocess
    import sys
    from pathlib import Path

    # Try package location first (installed)
    package_scripts = Path(sys.prefix) / "share" / "clerk" / "scripts"

    # Try relative to this file (development)
    dev_scripts = Path(__file__).parent.parent.parent / "scripts"

    script_path = None
    if (package_scripts / "install-workers.sh").exists():
        script_path = package_scripts / "install-workers.sh"
    elif (dev_scripts / "install-workers.sh").exists():
        script_path = dev_scripts / "install-workers.sh"
    else:
        click.secho("Error: install-workers.sh script not found", fg="red")
        raise click.Abort()

    # Execute the script
    result = subprocess.run(
        [str(script_path)],
        cwd=Path.cwd(),  # Run in current directory (where .env is)
    )
    sys.exit(result.returncode)


@cli.command()
def uninstall_workers():
    """Uninstall RQ worker background services (macOS/Linux)."""
    import subprocess
    import sys
    from pathlib import Path

    # Try package location first (installed)
    package_scripts = Path(sys.prefix) / "share" / "clerk" / "scripts"

    # Try relative to this file (development)
    dev_scripts = Path(__file__).parent.parent.parent / "scripts"

    script_path = None
    if (package_scripts / "uninstall-workers.sh").exists():
        script_path = package_scripts / "uninstall-workers.sh"
    elif (dev_scripts / "uninstall-workers.sh").exists():
        script_path = dev_scripts / "uninstall-workers.sh"
    else:
        click.secho("Error: uninstall-workers.sh script not found", fg="red")
        raise click.Abort()

    # Execute the script
    result = subprocess.run(
        [str(script_path)],
        cwd=Path.cwd(),  # Run in current directory (where .env is)
    )
    sys.exit(result.returncode)


@cli.command()
def reload_workers():
    """Reload RQ worker background services after code changes (macOS/Linux)."""
    import subprocess
    import sys
    from pathlib import Path

    # Try package location first (installed)
    package_scripts = Path(sys.prefix) / "share" / "clerk" / "scripts"

    # Try relative to this file (development)
    dev_scripts = Path(__file__).parent.parent.parent / "scripts"

    script_path = None
    if (package_scripts / "reload-workers.sh").exists():
        script_path = package_scripts / "reload-workers.sh"
    elif (dev_scripts / "reload-workers.sh").exists():
        script_path = dev_scripts / "reload-workers.sh"
    else:
        click.secho("Error: reload-workers.sh script not found", fg="red")
        raise click.Abort()

    # Execute the script
    result = subprocess.run(
        [str(script_path)],
        cwd=Path.cwd(),  # Run in current directory (where .env is)
    )
    sys.exit(result.returncode)


@cli.command()
@click.option("--reset", is_flag=True, help="Reset orphaned sites to initial state")
@click.option("--reenqueue", is_flag=True, help="Re-enqueue orphaned sites for processing")
@click.option("--max-age", default=2, help="Consider sites orphaned after N hours (default: 2)")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def cleanup_orphaned(reset, reenqueue, max_age, output_json):
    """Find and clean up orphaned jobs.

    Orphaned jobs are sites where the status indicates work in progress
    (fetching, needs_ocr, etc.) but no job is actually running in the queue.

    This can happen when:
    - Workers crash mid-job
    - Jobs fail silently without updating status
    - Redis is cleared but database isn't

    Examples:
        # List orphaned sites
        clerk cleanup-orphaned

        # Reset orphaned sites to initial state
        clerk cleanup-orphaned --reset

        # Reset and re-enqueue for processing
        clerk cleanup-orphaned --reset --reenqueue

        # Only consider sites orphaned after 4 hours
        clerk cleanup-orphaned --max-age 4
    """
    from datetime import datetime, timedelta

    import redis
    from sqlalchemy import text

    from .db import civic_db_connection, update_site
    from .queue import get_redis
    from .queue_db import get_jobs_for_site

    try:
        redis_client = get_redis()
        redis_client.ping()
    except (redis.ConnectionError, redis.TimeoutError) as e:
        click.secho(f"✗ Cannot connect to Redis: {e}", fg="red")
        return

    orphaned_sites = []

    with civic_db_connection() as conn:
        # Find sites with in-progress status that are old enough
        cutoff_time = datetime.now(UTC) - timedelta(hours=max_age)
        query = text("""
            SELECT subdomain, status, last_updated
            FROM sites
            WHERE status IN ('fetching', 'needs_ocr', 'needs_compilation', 'needs_deploy', 'extracting')
              AND last_updated::timestamp < :cutoff_time
            ORDER BY last_updated ASC
        """)

        for row in conn.execute(query, {"cutoff_time": cutoff_time}):
            subdomain = row[0]
            status = row[1]
            last_updated_str = row[2]

            # Parse last_updated string to datetime for stale calculation
            last_updated = None
            if last_updated_str:
                try:
                    last_updated = datetime.fromisoformat(last_updated_str).replace(tzinfo=UTC)
                except Exception:
                    pass

            # Check if there are any jobs for this site in any queue
            jobs = get_jobs_for_site(conn, subdomain)

            # Check if any job is actually running
            has_active_job = False
            for job_data in jobs:
                job_id = job_data.get("job_id")
                if job_id:
                    # Check if job exists in Redis
                    try:
                        from rq.job import Job

                        job = Job.fetch(job_id, connection=redis_client)
                        if job.get_status() in ["queued", "started"]:
                            has_active_job = True
                            break
                    except Exception:
                        # Job doesn't exist in Redis
                        pass

            if not has_active_job:
                orphaned_sites.append(
                    {
                        "subdomain": subdomain,
                        "status": status,
                        "last_updated": last_updated_str if last_updated_str else "unknown",
                        "stale_for": str(datetime.now(UTC) - last_updated)
                        if last_updated
                        else "unknown",
                    }
                )

    if output_json:
        import json

        result = {
            "orphaned_count": len(orphaned_sites),
            "sites": orphaned_sites,
            "actions": {
                "reset": reset,
                "reenqueue": reenqueue,
            },
        }
        click.echo(json.dumps(result, indent=2))
    else:
        if not orphaned_sites:
            click.secho("✓ No orphaned sites found", fg="green")
            return

        click.secho(f"\n⚠️  Found {len(orphaned_sites)} orphaned sites:\n", fg="yellow", bold=True)

        for site in orphaned_sites:
            click.echo(f"  • {site['subdomain']}: {site['status']} - stale for {site['stale_for']}")

    if orphaned_sites and (reset or reenqueue):
        click.echo()

        if reset:
            click.secho(f"🔄 Resetting {len(orphaned_sites)} orphaned sites...", fg="cyan")
            with civic_db_connection() as conn:
                for site in orphaned_sites:
                    update_site(
                        conn,
                        site["subdomain"],
                        {
                            "status": None,
                            "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                        },
                    )
                    click.echo(f"  ✓ Reset {site['subdomain']}")

        if reenqueue:
            from .queue import get_high_queue

            click.secho(f"📥 Re-enqueueing {len(orphaned_sites)} sites...", fg="cyan")
            high_queue = get_high_queue()

            for site in orphaned_sites:
                from .workers import fetch_site_job

                job = high_queue.enqueue(
                    fetch_site_job,
                    subdomain=site["subdomain"],
                    run_id=f"retry_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    job_timeout="30m",
                    description=f"Retry orphaned: {site['subdomain']}",
                )
                click.echo(f"  ✓ Enqueued {site['subdomain']} (job: {job.id})")

        click.echo()
        click.secho("✅ Cleanup complete", fg="green", bold=True)


@cli.command()
@click.option("--queue", default="ocr", help="Queue to check (default: ocr)")
@click.option("--limit", default=5, help="Number of failed jobs to show (default: 5)")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def check_failed(queue, limit, output_json):
    """Check failed jobs in a queue and show error details.

    Examples:
        # Check OCR failures
        clerk check-failed

        # Check first 10 fetch failures
        clerk check-failed --queue fetch --limit 10

        # Get JSON output
        clerk check-failed --json
    """
    import redis
    from rq.job import Job
    from rq.registry import FailedJobRegistry

    from .queue import get_redis

    try:
        redis_client = get_redis()
        redis_client.ping()
    except (redis.ConnectionError, redis.TimeoutError) as e:
        click.secho(f"✗ Cannot connect to Redis: {e}", fg="red")
        return

    failed_reg = FailedJobRegistry(queue, connection=redis_client)
    total_failures = len(failed_reg)

    failed_jobs = []
    for job_id in list(failed_reg.get_job_ids())[:limit]:
        try:
            job = Job.fetch(job_id, connection=redis_client)
            exc_info = None
            if job.exc_info:
                # Get full traceback for debugging
                exc_info = job.exc_info.strip()

            failed_jobs.append(
                {
                    "job_id": job_id,
                    "description": job.description,
                    "exc_info": exc_info,
                    "status": job.get_status(),
                    "created_at": str(job.created_at) if job.created_at else None,
                    "ended_at": str(job.ended_at) if job.ended_at else None,
                    "args": job.args,
                    "kwargs": job.kwargs,
                    "meta": job.meta,
                }
            )
        except Exception as e:
            failed_jobs.append(
                {
                    "job_id": job_id,
                    "description": "Could not fetch job details",
                    "exc_info": str(e),
                    "status": "unknown",
                    "created_at": None,
                    "ended_at": None,
                    "meta": {},
                }
            )

    if output_json:
        result = {
            "queue": queue,
            "total_failures": total_failures,
            "showing": len(failed_jobs),
            "failed_jobs": failed_jobs,
        }
        click.echo(json.dumps(result, indent=2))
    else:
        click.secho(f"\n{'=' * 60}", fg="cyan")
        click.secho(f"Failed Jobs in '{queue}' Queue", fg="cyan", bold=True)
        click.secho(f"{'=' * 60}\n", fg="cyan")

        click.echo(f"Total failures: {total_failures}")
        click.echo(f"Showing first {len(failed_jobs)} jobs:\n")

        for i, job_info in enumerate(failed_jobs, 1):
            click.secho(f"{i}. {job_info['description']}", fg="yellow", bold=True)
            click.echo(f"   Job ID: {job_info['job_id']}")
            click.echo(f"   Status: {job_info.get('status', 'unknown')}")

            # Show job arguments (subdomain, pdf_path, etc.)
            if job_info.get("kwargs"):
                kwargs = job_info["kwargs"]
                if "subdomain" in kwargs:
                    click.echo(f"   Subdomain: {kwargs['subdomain']}")
                if "pdf_path" in kwargs:
                    click.echo(f"   PDF Path: {kwargs['pdf_path']}")

            if job_info.get("created_at"):
                click.echo(f"   Created: {job_info['created_at']}")
            if job_info.get("ended_at"):
                click.echo(f"   Ended: {job_info['ended_at']}")
            if job_info["exc_info"]:
                click.secho("   Error:", fg="red")
                for line in job_info["exc_info"].split("\n"):
                    click.echo(f"     {line}")
            else:
                click.secho("   (No exception info available)", dim=True)
            click.echo()


@cli.command()
@click.option("--threshold-hours", default=2, help="Hours since update to consider stuck")
@click.option(
    "--dry-run", is_flag=True, default=False, help="Show what would be done without making changes"
)
def reconcile_pipeline(threshold_hours, dry_run):
    """Detect and recover stuck sites in pipeline.

    This command:
    1. Finds sites with stale updated_at timestamps
    2. Infers actual state from filesystem
    3. Enqueues missing coordinators
    4. Re-enqueues lost jobs

    Run this periodically (every 15 minutes) via cron.

    Examples:
        # Check for sites stuck >2 hours
        clerk reconcile-pipeline

        # Check for sites stuck >6 hours (dry run)
        clerk reconcile-pipeline --threshold-hours 6 --dry-run

        # Preview what would be recovered
        clerk reconcile-pipeline --dry-run
    """
    from datetime import UTC, datetime

    from . import migrations

    click.echo("=" * 80)
    click.echo(f"RECONCILIATION: {datetime.now(UTC).isoformat()}")
    click.echo("=" * 80)
    click.echo()

    if dry_run:
        click.secho("DRY RUN MODE - no changes will be made", fg="yellow")
        click.echo()

    # Find stuck sites
    stuck = migrations.find_stuck_sites(threshold_hours)

    if not stuck:
        click.echo("No stuck sites found")
        return

    click.echo(f"Found {len(stuck)} stuck sites:")
    click.echo()

    # Recover each stuck site
    recovered = 0
    for site in stuck:
        if not dry_run:
            if migrations.recover_stuck_site(site.subdomain):
                recovered += 1
        else:
            click.echo(f"  {site.subdomain}: Would recover (dry run)")

    click.echo()
    if dry_run:
        click.secho(f"Would recover {len(stuck)} sites", fg="yellow")
    else:
        click.secho(f"Recovered {recovered} sites", fg="green")


@cli.command()
def pipeline_status():
    """Show comprehensive pipeline health and status.

    Shows:
    - Pipeline stage distribution
    - Sites marked as no_documents
    - Stuck sites (not updated in 2+ hours)
    - Success metrics and completion rates

    Examples:
        # Show current pipeline status
        clerk pipeline-status
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, select

    from .models import sites_table

    click.echo("=" * 80)
    click.echo("PIPELINE STATUS")
    click.echo("=" * 80)
    click.echo()

    with civic_db_connection() as conn:
        # 1. Stage distribution
        click.echo("Pipeline Stage Distribution:")
        click.echo("-" * 40)

        stage_counts = conn.execute(
            select(sites_table.c.current_stage, func.count().label("count"))
            .where(sites_table.c.current_stage.isnot(None))
            .group_by(sites_table.c.current_stage)
        ).fetchall()

        total_in_pipeline = sum(row.count for row in stage_counts)  # type: ignore

        for row in sorted(stage_counts, key=lambda x: x.count, reverse=True):  # type: ignore
            stage = row.current_stage or "none"
            count = row.count
            pct = (count / total_in_pipeline * 100) if total_in_pipeline > 0 else 0
            click.echo(f"  {stage:20s}: {count:4d} ({pct:5.1f}%)")

        click.echo()

        # 2. No documents sites
        no_docs_count = conn.execute(
            select(func.count())
            .select_from(sites_table)
            .where(sites_table.c.status == "no_documents")
        ).scalar()

        if no_docs_count and no_docs_count > 0:
            click.secho(f"Sites with No Documents: {no_docs_count}", fg="yellow")
            click.echo()

        # 3. Stuck sites (not updated in 2+ hours, not completed)
        cutoff = datetime.now(UTC) - timedelta(hours=2)
        stuck = conn.execute(
            select(func.count())
            .select_from(sites_table)
            .where(
                sites_table.c.current_stage != "completed",
                sites_table.c.current_stage.isnot(None),
                sites_table.c.updated_at < cutoff,
            )
        ).scalar()

        if stuck and stuck > 0:
            click.secho(f"⚠️  Stuck Sites (>2h no update): {stuck}", fg="yellow")
            click.echo("  Run: clerk reconcile-pipeline")
            click.echo()
        else:
            click.secho("✓ No stuck sites found", fg="green")
            click.echo()

        # 4. Success metrics
        click.echo("OCR Success Metrics:")
        click.echo("-" * 40)

        ocr_stats = conn.execute(
            select(
                func.sum(sites_table.c.ocr_total).label("total_jobs"),
                func.sum(sites_table.c.ocr_completed).label("completed"),
                func.sum(sites_table.c.ocr_failed).label("failed"),
            ).where(sites_table.c.ocr_total > 0)
        ).fetchone()

        if ocr_stats and ocr_stats.total_jobs:
            total = ocr_stats.total_jobs or 0
            completed = ocr_stats.completed or 0
            failed = ocr_stats.failed or 0

            success_rate = (completed / total * 100) if total > 0 else 0
            failure_rate = (failed / total * 100) if total > 0 else 0

            click.echo(f"  Total OCR jobs:    {total:6d}")
            click.echo(f"  Completed:         {completed:6d} ({success_rate:5.1f}%)")
            click.echo(f"  Failed:            {failed:6d} ({failure_rate:5.1f}%)")
        else:
            click.echo("  No OCR jobs found")

        click.echo()

        # 5. Recent completions
        click.echo("Recent Activity (last 24h):")
        click.echo("-" * 40)

        day_ago = datetime.now(UTC) - timedelta(hours=24)
        recently_completed = conn.execute(
            select(func.count())
            .select_from(sites_table)
            .where(sites_table.c.current_stage == "completed", sites_table.c.updated_at >= day_ago)
        ).scalar()

        click.echo(f"  Sites completed: {recently_completed or 0}")
        click.echo()

        # 6. Sites in active stages
        click.echo("Active Processing:")
        click.echo("-" * 40)

        active_stages = ["ocr", "compilation", "extraction", "deploy"]
        for stage in active_stages:
            count = conn.execute(
                select(func.count())
                .select_from(sites_table)
                .where(sites_table.c.current_stage == stage)
            ).scalar()

            if count and count > 0:
                click.echo(f"  {stage.capitalize():15s}: {count:4d} sites processing")

    click.echo()
    click.echo("=" * 80)


cli.add_command(extract)
cli.add_command(db)
cli.add_command(debug)
cli.add_command(etl)
