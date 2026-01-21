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

    Connection parameters (configurable via environment):
    - REDIS_SOCKET_CONNECT_TIMEOUT: Connection timeout in seconds (default: 30)
    - REDIS_SOCKET_TIMEOUT: Socket read/write timeout in seconds (default: 30)
    - REDIS_SOCKET_KEEPALIVE: Enable TCP keepalive (default: true)
    - REDIS_CONNECTION_RETRIES: Number of connection attempts (default: 3)

    Raises:
        RuntimeError: If Redis connection cannot be established after retries.
    """
    global _redis_client

    if _redis_client is None:
        with _redis_lock:
            # Double-check: another thread might have initialized
            if _redis_client is None:
                redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

                # Configurable connection parameters
                socket_connect_timeout = int(os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT", "30"))
                socket_timeout = int(os.getenv("REDIS_SOCKET_TIMEOUT", "30"))
                socket_keepalive = os.getenv("REDIS_SOCKET_KEEPALIVE", "true").lower() == "true"
                max_retries = int(os.getenv("REDIS_CONNECTION_RETRIES", "3"))

                # Build connection with resilience settings
                connection_kwargs = {
                    "socket_connect_timeout": socket_connect_timeout,
                    "socket_timeout": socket_timeout,
                    "socket_keepalive": socket_keepalive,
                    "retry_on_timeout": True,  # Retry reads/writes on timeout
                    "health_check_interval": 30,  # Check connection health every 30s
                }

                last_error = None
                for attempt in range(1, max_retries + 1):
                    try:
                        # NOTE: Do NOT use decode_responses=True - RQ is incompatible
                        # RQ stores pickled binary data, which causes UnicodeDecodeError
                        # when Redis tries to decode it as UTF-8
                        client = redis.from_url(redis_url, **connection_kwargs)
                        client.ping()  # Test connection
                        _redis_client = client

                        if attempt > 1:
                            print(
                                f"Successfully connected to Redis on attempt {attempt}",
                                file=sys.stderr,
                            )
                        return _redis_client
                    except (redis.ConnectionError, redis.TimeoutError) as e:
                        last_error = e
                        if attempt < max_retries:
                            wait_time = 2**attempt  # Exponential backoff: 2, 4, 8 seconds
                            print(
                                f"Redis connection attempt {attempt}/{max_retries} failed: {e}",
                                file=sys.stderr,
                            )
                            print(f"Retrying in {wait_time}s...", file=sys.stderr)
                            time.sleep(wait_time)
                        else:
                            print(
                                f"ERROR: Cannot connect to Redis after {max_retries} attempts: {e}",
                                file=sys.stderr,
                            )
                            print(f"REDIS_URL: {redis_url}", file=sys.stderr)

                # All retries exhausted
                error_msg = f"Failed to connect to Redis after {max_retries} attempts: {last_error}"
                raise RuntimeError(error_msg) from last_error

    return _redis_client


def generate_run_id(subdomain):
    timestamp = int(time.time())
    random_suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{subdomain}_{timestamp}_{random_suffix}"


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
        run_id = generate_run_id(site_id)

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
