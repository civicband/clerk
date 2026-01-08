# tests/test_queue.py
from unittest.mock import MagicMock, patch

import pytest


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


def test_get_queues_returns_queue_objects(reset_redis_singleton):
    """Test that queue getters return RQ Queue objects."""
    with patch('clerk.queue.get_redis') as mock_get_redis:
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis

        from rq import Queue

        from clerk.queue import (
            get_deploy_queue,
            get_extraction_queue,
            get_fetch_queue,
            get_high_queue,
            get_ocr_queue,
        )

        # Test all 5 queues
        high_queue = get_high_queue()
        fetch_queue = get_fetch_queue()
        ocr_queue = get_ocr_queue()
        extraction_queue = get_extraction_queue()
        deploy_queue = get_deploy_queue()

        # Verify all are Queue instances
        assert isinstance(high_queue, Queue)
        assert isinstance(fetch_queue, Queue)
        assert isinstance(ocr_queue, Queue)
        assert isinstance(extraction_queue, Queue)
        assert isinstance(deploy_queue, Queue)

        # Verify correct names
        assert high_queue.name == 'high'
        assert fetch_queue.name == 'fetch'
        assert ocr_queue.name == 'ocr'
        assert extraction_queue.name == 'extraction'
        assert deploy_queue.name == 'deploy'


def test_enqueue_job_adds_to_correct_queue(reset_redis_singleton):
    """Test that enqueue_job routes jobs to correct queue based on priority."""
    # Mock workers module that doesn't exist yet
    mock_workers_module = MagicMock()
    mock_workers_module.fetch_site_job = MagicMock()

    import sys
    sys.modules['clerk.workers'] = mock_workers_module

    try:
        from clerk.queue import enqueue_job

        with patch('clerk.queue.get_high_queue') as mock_high, \
             patch('clerk.queue.get_fetch_queue') as mock_fetch:

            mock_high_queue = MagicMock()
            mock_fetch_queue = MagicMock()
            mock_high.return_value = mock_high_queue
            mock_fetch.return_value = mock_fetch_queue

            mock_high_queue.enqueue.return_value = MagicMock(id='job-high-123')
            mock_fetch_queue.enqueue.return_value = MagicMock(id='job-fetch-456')

            # High priority goes to express queue
            job_id = enqueue_job('fetch-site', 'site.civic.band', priority='high')
            assert job_id == 'job-high-123'
            mock_high_queue.enqueue.assert_called_once()

            # Reset for next test
            mock_high_queue.reset_mock()
            mock_fetch_queue.reset_mock()

            # Normal priority goes to stage queue
            job_id = enqueue_job('fetch-site', 'site.civic.band', priority='normal')
            assert job_id == 'job-fetch-456'
            mock_fetch_queue.enqueue.assert_called_once()
    finally:
        # Clean up the mock module
        if 'clerk.workers' in sys.modules:
            del sys.modules['clerk.workers']
