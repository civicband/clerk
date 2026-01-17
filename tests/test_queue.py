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
    with patch("clerk.queue.redis.from_url") as mock_redis:
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_redis.return_value = mock_client

        from clerk.queue import get_redis

        client = get_redis()

        assert client == mock_client
        mock_redis.assert_called_once()
        mock_client.ping.assert_called_once()


def test_get_redis_no_decode_responses(reset_redis_singleton):
    """Test that get_redis does NOT use decode_responses=True.

    RQ is incompatible with decode_responses=True because it stores
    pickled binary data in Redis. Enabling decode_responses causes
    UnicodeDecodeError when workers try to fetch jobs.
    """
    with patch("clerk.queue.redis.from_url") as mock_redis:
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_redis.return_value = mock_client

        from clerk.queue import get_redis

        get_redis()

        # Verify redis.from_url was called WITHOUT decode_responses=True
        mock_redis.assert_called_once()
        call_args = mock_redis.call_args

        # Check that decode_responses is either not present or explicitly False
        if len(call_args.args) > 1:
            # Positional args - should not have decode_responses
            assert len(call_args.args) == 1  # Only redis_url

        # Check keyword arguments
        assert call_args.kwargs.get("decode_responses") is not True


def test_get_redis_singleton_behavior(reset_redis_singleton):
    """Test that get_redis returns the same instance on multiple calls."""
    with patch("clerk.queue.redis.from_url") as mock_redis:
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
    with patch("clerk.queue.get_redis") as mock_get_redis:
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
        assert high_queue.name == "high"
        assert fetch_queue.name == "fetch"
        assert ocr_queue.name == "ocr"
        assert extraction_queue.name == "extraction"
        assert deploy_queue.name == "deploy"


def test_enqueue_job_adds_to_correct_queue(reset_redis_singleton):
    """Test that enqueue_job routes jobs to correct queue based on priority."""
    # Mock Redis connection at the lowest level to prevent any actual connection attempts
    with patch("clerk.queue.redis.from_url") as mock_redis_from_url:
        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True
        mock_redis_from_url.return_value = mock_redis_client

        # Mock workers module that doesn't exist yet
        mock_workers_module = MagicMock()
        mock_workers_module.fetch_site_job = MagicMock()

        import sys

        sys.modules["clerk.workers"] = mock_workers_module

        try:
            from clerk.queue import enqueue_job

            with (
                patch("clerk.queue.get_high_queue") as mock_high,
                patch("clerk.queue.get_fetch_queue") as mock_fetch,
            ):
                mock_high_queue = MagicMock()
                mock_fetch_queue = MagicMock()
                mock_high.return_value = mock_high_queue
                mock_fetch.return_value = mock_fetch_queue

                mock_high_queue.enqueue.return_value = MagicMock(id="job-high-123")
                mock_fetch_queue.enqueue.return_value = MagicMock(id="job-fetch-456")

                # High priority goes to express queue
                job_id = enqueue_job("fetch-site", "site.civic.band", priority="high")
                assert job_id == "job-high-123"
                mock_high_queue.enqueue.assert_called_once()

                # Reset for next test
                mock_high_queue.reset_mock()
                mock_fetch_queue.reset_mock()

                # Normal priority goes to stage queue
                job_id = enqueue_job("fetch-site", "site.civic.band", priority="normal")
                assert job_id == "job-fetch-456"
                mock_fetch_queue.enqueue.assert_called_once()
        finally:
            # Clean up the mock module
            if "clerk.workers" in sys.modules:
                del sys.modules["clerk.workers"]


def test_enqueue_job_generates_run_id(mocker):
    """Test that enqueue_job generates run_id if not provided."""
    # Mock Redis to avoid connection attempt
    mocker.patch('clerk.queue.get_redis')

    mock_queue = mocker.MagicMock()
    mock_queue.enqueue.return_value = mocker.MagicMock(id="job-123")
    mocker.patch('clerk.queue.get_fetch_queue', return_value=mock_queue)

    from clerk.queue import enqueue_job

    enqueue_job("fetch-site", "test.civic.band", priority="normal")

    # Verify enqueue was called with run_id in kwargs
    call_kwargs = mock_queue.enqueue.call_args[1]
    assert 'run_id' in call_kwargs

    # Verify format: subdomain_timestamp_random
    run_id = call_kwargs['run_id']
    parts = run_id.split('_')
    assert parts[0] == "test.civic.band"
    assert parts[1].isdigit()  # timestamp
    assert len(parts[2]) == 6  # random suffix


def test_enqueue_job_uses_provided_run_id(mocker):
    """Test that enqueue_job uses run_id if provided."""
    # Mock Redis to avoid connection attempt
    mocker.patch('clerk.queue.get_redis')

    mock_queue = mocker.MagicMock()
    mock_queue.enqueue.return_value = mocker.MagicMock(id="job-123")
    mocker.patch('clerk.queue.get_fetch_queue', return_value=mock_queue)

    from clerk.queue import enqueue_job

    custom_run_id = "custom_12345_xyz123"
    enqueue_job("fetch-site", "test.civic.band", priority="normal", run_id=custom_run_id)

    # Verify enqueue was called with custom run_id
    call_kwargs = mock_queue.enqueue.call_args[1]
    assert call_kwargs['run_id'] == custom_run_id


def test_run_id_format_is_unique(mocker):
    """Test that generated run_ids are unique."""
    # Mock Redis to avoid connection attempt
    mocker.patch('clerk.queue.get_redis')

    mock_queue = mocker.MagicMock()
    mock_queue.enqueue.return_value = mocker.MagicMock(id="job-123")
    mocker.patch('clerk.queue.get_fetch_queue', return_value=mock_queue)

    from clerk.queue import enqueue_job

    # Generate two run_ids
    enqueue_job("fetch-site", "test.civic.band", priority="normal")
    run_id_1 = mock_queue.enqueue.call_args[1]['run_id']

    enqueue_job("fetch-site", "test.civic.band", priority="normal")
    run_id_2 = mock_queue.enqueue.call_args[1]['run_id']

    # Should be different
    assert run_id_1 != run_id_2
