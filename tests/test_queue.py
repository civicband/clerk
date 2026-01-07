# tests/test_queue.py
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def reset_redis_singleton():
    """Reset the Redis singleton state before each test."""
    import clerk.queue
    clerk.queue._redis_client = None
    yield
    clerk.queue._redis_client = None


def test_get_redis_returns_client(reset_redis_singleton):
    """Test that get_redis returns a Redis client."""
    with patch('clerk.queue.redis.from_url') as mock_redis:
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_redis.return_value = mock_client

        from clerk.queue import get_redis
        client = get_redis()

        assert client == mock_client
        mock_redis.assert_called_once()
        mock_client.ping.assert_called_once()


def test_get_redis_singleton_behavior(reset_redis_singleton):
    """Test that get_redis returns the same instance on multiple calls."""
    with patch('clerk.queue.redis.from_url') as mock_redis:
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_redis.return_value = mock_client

        from clerk.queue import get_redis

        client1 = get_redis()
        client2 = get_redis()

        assert client1 is client2
        mock_redis.assert_called_once()  # Only called once
        mock_client.ping.assert_called_once()  # Only called once
