#!/usr/bin/env python3
"""Check failed OCR jobs to diagnose why they failed."""

from clerk.queue import get_ocr_queue

ocr_q = get_ocr_queue()
failed = ocr_q.failed_job_registry

print(f"Total failed OCR jobs: {len(failed)}")
print()

# Get first 10 failed jobs
for job_id in list(failed.get_job_ids())[:10]:
    job = ocr_q.fetch_job(job_id)
    if job:
        subdomain = job.kwargs.get("subdomain", "unknown")
        pdf_path = job.kwargs.get("pdf_path", "unknown")

        print(f"Job ID: {job_id}")
        print(f"Subdomain: {subdomain}")
        print(f"PDF path: {pdf_path}")
        print(f"Error type: {job.exc_info.split(':')[0] if job.exc_info else 'unknown'}")

        # Print first 200 chars of error
        if job.exc_info:
            error_preview = job.exc_info[:200].replace('\n', ' ')
            print(f"Error preview: {error_preview}")

        print("-" * 80)
        print()
