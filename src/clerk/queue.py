# src/clerk/queue.py
"""Queue management using RQ (Redis Queue)."""

import os
import sys
import threading
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
                    client = redis.from_url(redis_url, decode_responses=True)
                    client.ping()  # Test connection
                    _redis_client = client
                except (redis.ConnectionError, redis.TimeoutError) as e:
                    print(f"ERROR: Cannot connect to Redis: {e}", file=sys.stderr)
                    print(f"REDIS_URL: {redis_url}", file=sys.stderr)
                    sys.exit(1)

    return _redis_client


def get_high_queue():
    """Get high-priority queue (express lane)."""
    return Queue('high', connection=get_redis())


def get_fetch_queue():
    """Get fetch jobs queue."""
    return Queue('fetch', connection=get_redis())


def get_ocr_queue():
    """Get OCR jobs queue."""
    return Queue('ocr', connection=get_redis())


def get_extraction_queue():
    """Get extraction jobs queue."""
    return Queue('extraction', connection=get_redis())


def get_deploy_queue():
    """Get deploy jobs queue."""
    return Queue('deploy', connection=get_redis())
