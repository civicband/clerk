# tests/test_queue.py
import pytest
from unittest.mock import patch, MagicMock


def test_get_redis_returns_client():
    """Test that get_redis returns a Redis client."""
    with patch('clerk.queue.redis.from_url') as mock_redis:
        mock_client = MagicMock()
        mock_redis.return_value = mock_client

        from clerk.queue import get_redis
        client = get_redis()

        assert client == mock_client
        mock_redis.assert_called_once()
