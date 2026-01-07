# src/clerk/queue.py
"""Queue management using RQ (Redis Queue)."""

import os
import redis

# Global Redis client
_redis_client = None


def get_redis():
    """Get Redis client singleton.

    Uses REDIS_URL environment variable for connection.
    Defaults to redis://localhost:6379 if not set.
    """
    global _redis_client
    if _redis_client is None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        _redis_client = redis.from_url(redis_url, decode_responses=True)
    return _redis_client
