#!/usr/bin/env python3
"""Diagnostic script to understand pipeline state issues."""

from collections import defaultdict

from sqlalchemy import select

from clerk.db import civic_db_connection
from clerk.models import site_progress_table, sites_table
from clerk.queue import (
    get_compilation_queue,
    get_deploy_queue,
    get_extraction_queue,
    get_fetch_queue,
    get_ocr_queue,
)

print("=" * 80)
print("EVIDENCE 1: Site Progress State")
print("=" * 80)

with civic_db_connection() as conn:
    stmt = select(site_progress_table)
    results = conn.execute(stmt).fetchall()

    by_stage = defaultdict(list)
    for row in results:
        by_stage[row.current_stage].append(row.subdomain)

    print(f"Total sites in site_progress: {len(results)}")
    print("\nBreakdown by stage:")
    for stage, sites in sorted(by_stage.items()):
        print(f"  {stage}: {len(sites)}")

    non_completed = [r for r in results if r.current_stage != "completed"]
    print(f"\nNot completed: {len(non_completed)}")
    print("\nFirst 5 non-completed:")
    for row in non_completed[:5]:
        print(
            f"  {row.subdomain}: {row.current_stage} ({row.stage_completed}/{row.stage_total}) updated {row.updated_at}"
        )

print("\n" + "=" * 80)
print("EVIDENCE 2: Sites Table Status")
print("=" * 80)

with civic_db_connection() as conn:
    stmt = select(sites_table)
    results = conn.execute(stmt).fetchall()

    by_status = defaultdict(list)
    for row in results:
        by_status[row.status or "NULL"].append(row.subdomain)

    print(f"Total sites: {len(results)}")
    for status, sites in sorted(by_status.items()):
        print(f"  {status}: {len(sites)}")

print("\n" + "=" * 80)
print("EVIDENCE 3: Deferred Jobs")
print("=" * 80)

queues = {
    "fetch": get_fetch_queue(),
    "ocr": get_ocr_queue(),
    "compilation": get_compilation_queue(),
    # "extraction": get_extraction_queue(),
    "deploy": get_deploy_queue(),
}

for name, queue in queues.items():
    deferred = queue.deferred_job_registry
    count = len(deferred)
    if count > 0:
        print(f"\n{name}: {count} deferred")
        for job_id in list(deferred.get_job_ids())[:3]:
            job = queue.fetch_job(job_id)
            if job:
                print(f"  {job.func_name} - {job.args[0] if job.args else 'no-args'}")

print("\n" + "=" * 80)
print("EVIDENCE 4: Active Queues")
print("=" * 80)

for name, queue in queues.items():
    print(
        f"{name}: active={len(queue)} started={len(queue.started_job_registry)} failed={len(queue.failed_job_registry)}"
    )
