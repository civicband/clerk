def test_fetch_site_job_exists():
    """Test that fetch_site_job function exists."""
    from clerk.workers import fetch_site_job

    assert callable(fetch_site_job)


def test_ocr_page_job_exists():
    """Test that ocr_page_job function exists."""
    from clerk.workers import ocr_page_job

    assert callable(ocr_page_job)


def test_log_with_context_includes_job_context(mocker):
    """Test that log_with_context extracts job_id and parent_job_id from RQ context."""
    from clerk.workers import log_with_context

    # Mock get_current_job to return a job with ID and dependency
    mock_job = mocker.MagicMock()
    mock_job.id = "job-123"
    mock_job.dependency_id = "job-456"
    mocker.patch('clerk.workers.get_current_job', return_value=mock_job)

    # Mock output_log
    mock_output_log = mocker.patch('clerk.workers.output_log')

    log_with_context(
        "test message",
        subdomain="test.civic.band",
        run_id="test_123_abc",
        stage="fetch"
    )

    # Verify output_log was called with job context
    mock_output_log.assert_called_once_with(
        "test message",
        subdomain="test.civic.band",
        run_id="test_123_abc",
        stage="fetch",
        job_id="job-123",
        parent_job_id="job-456"
    )


def test_log_with_context_handles_no_job(mocker):
    """Test that log_with_context works when no RQ job context exists."""
    from clerk.workers import log_with_context

    # Mock get_current_job to return None (no job context)
    mocker.patch('clerk.workers.get_current_job', return_value=None)

    # Mock output_log
    mock_output_log = mocker.patch('clerk.workers.output_log')

    log_with_context(
        "test message",
        subdomain="test.civic.band",
        run_id="test_123_abc",
        stage="fetch"
    )

    # Verify output_log was called with None for job fields
    mock_output_log.assert_called_once_with(
        "test message",
        subdomain="test.civic.band",
        run_id="test_123_abc",
        stage="fetch",
        job_id=None,
        parent_job_id=None
    )


def test_log_with_context_passes_extra_kwargs(mocker):
    """Test that log_with_context passes through additional kwargs."""
    from clerk.workers import log_with_context

    mocker.patch('clerk.workers.get_current_job', return_value=None)
    mock_output_log = mocker.patch('clerk.workers.output_log')

    log_with_context(
        "test message",
        subdomain="test.civic.band",
        run_id="test_123_abc",
        stage="fetch",
        total_pdfs=47,
        duration_seconds=120.5
    )

    # Verify extra kwargs were passed through
    call_kwargs = mock_output_log.call_args[1]
    assert call_kwargs['total_pdfs'] == 47
    assert call_kwargs['duration_seconds'] == 120.5


def test_db_compilation_job_accepts_run_id(mocker):
    """Test that db_compilation_job accepts run_id parameter."""
    from clerk.workers import db_compilation_job

    mocker.patch('clerk.workers.civic_db_connection')
    mocker.patch('clerk.utils.build_db_from_text_internal')
    mocker.patch('clerk.queue_db.update_site_progress')
    mocker.patch('clerk.queue.get_deploy_queue')
    mocker.patch('clerk.queue_db.track_job')
    mock_log = mocker.patch('clerk.workers.log_with_context')

    db_compilation_job("test.civic.band", run_id="test_123_abc", extract_entities=False)

    assert any(call[1]['stage'] == 'compilation' for call in mock_log.call_args_list)


def test_db_compilation_job_passes_run_id_to_deploy(mocker):
    """Test that db_compilation_job passes run_id to deploy job."""
    from clerk.workers import db_compilation_job

    mocker.patch('clerk.workers.civic_db_connection')
    mocker.patch('clerk.utils.build_db_from_text_internal')
    mocker.patch('clerk.queue_db.update_site_progress')
    mocker.patch('clerk.queue_db.track_job')
    mocker.patch('clerk.workers.log_with_context')

    mock_deploy_queue = mocker.MagicMock()
    mock_deploy_job = mocker.MagicMock(id="deploy-job-123")
    mock_deploy_queue.enqueue.return_value = mock_deploy_job
    mocker.patch('clerk.queue.get_deploy_queue', return_value=mock_deploy_queue)

    db_compilation_job("test.civic.band", run_id="test_123_abc", extract_entities=False)

    call_kwargs = mock_deploy_queue.enqueue.call_args[1]
    assert call_kwargs['run_id'] == "test_123_abc"
