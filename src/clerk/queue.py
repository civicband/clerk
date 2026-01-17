# src/clerk/queue.py
"""Queue management using RQ (Redis Queue)."""

import os
import random
import string
import sys
import threading
import time

import redis
from rq import Queue

# Global Redis client
_redis_client = None
_redis_lock = threading.Lock()


def get_redis():
    """Get Redis client singleton.

    Uses REDIS_URL environment variable for connection.
    Defaults to redis://localhost:6379 if not set.

    Thread-safe initialization with double-checked locking.
    Validates connection on initialization (fail-fast).

    Raises:
        SystemExit: If Redis connection cannot be established.
    """
    global _redis_client

    if _redis_client is None:
        with _redis_lock:
            # Double-check: another thread might have initialized
            if _redis_client is None:
                redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
                try:
                    # NOTE: Do NOT use decode_responses=True - RQ is incompatible
                    # RQ stores pickled binary data, which causes UnicodeDecodeError
                    # when Redis tries to decode it as UTF-8
                    client = redis.from_url(redis_url)
                    client.ping()  # Test connection
                    _redis_client = client
                except (redis.ConnectionError, redis.TimeoutError) as e:
                    print(f"ERROR: Cannot connect to Redis: {e}", file=sys.stderr)
                    print(f"REDIS_URL: {redis_url}", file=sys.stderr)
                    sys.exit(1)

    return _redis_client


def get_high_queue():
    """Get high-priority queue (express lane)."""
    return Queue("high", connection=get_redis())


def get_fetch_queue():
    """Get fetch jobs queue."""
    return Queue("fetch", connection=get_redis())


def get_ocr_queue():
    """Get OCR jobs queue."""
    return Queue("ocr", connection=get_redis())


def get_compilation_queue():
    """Get compilation jobs queue (coordinator, db compilation)."""
    return Queue("compilation", connection=get_redis())


def get_extraction_queue():
    """Get extraction jobs queue."""
    return Queue("extraction", connection=get_redis())


def get_deploy_queue():
    """Get deploy jobs queue."""
    return Queue("deploy", connection=get_redis())


def enqueue_job(job_type, site_id, priority="normal", run_id=None, **kwargs):
    """Enqueue a job to the appropriate queue.

    Args:
        job_type: Type of job (fetch-site, ocr-page, etc.)
        site_id: Site subdomain
        priority: 'high', 'normal', or 'low'
        run_id: Optional pipeline run ID (auto-generated if not provided)
        **kwargs: Additional job parameters

    Returns:
        RQ job ID
    """
    # Generate run_id if not provided
    if run_id is None:
        timestamp = int(time.time())
        random_suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        run_id = f"{site_id}_{timestamp}_{random_suffix}"

    # Pass run_id to job function
    kwargs["run_id"] = run_id
    # Determine which queue to use
    if priority == "high":
        queue = get_high_queue()
    else:
        # Route to stage-specific queue based on job type
        stage = job_type.split("-")[0]  # fetch-site → fetch
        queue_map = {
            "fetch": get_fetch_queue(),
            "ocr": get_ocr_queue(),
            "compilation": get_compilation_queue(),
            "extraction": get_extraction_queue(),
            "deploy": get_deploy_queue(),
        }
        queue = queue_map.get(stage, get_fetch_queue())

    # Import worker function based on job type
    from . import workers

    job_function_map = {
        "fetch-site": workers.fetch_site_job,
        "ocr-page": workers.ocr_page_job,
        "extract-site": workers.extraction_job,
        "deploy-site": workers.deploy_job,
    }

    job_function = job_function_map.get(job_type)
    if not job_function:
        raise ValueError(f"Unknown job type: {job_type}")

    # Enqueue the job
    job = queue.enqueue(job_function, site_id, **kwargs)
    return job.id
