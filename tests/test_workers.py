def test_fetch_site_job_exists():
    """Test that fetch_site_job function exists."""
    from clerk.workers import fetch_site_job

    assert callable(fetch_site_job)


def test_ocr_page_job_exists():
    """Test that ocr_page_job function exists."""
    from clerk.workers import ocr_page_job

    assert callable(ocr_page_job)


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
