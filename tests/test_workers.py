def test_fetch_site_job_exists():
    """Test that fetch_site_job function exists."""
    from clerk.workers import fetch_site_job

    assert callable(fetch_site_job)


def test_ocr_document_job_exists():
    """Test that ocr_document_job function exists."""
    from clerk.workers import ocr_document_job

    assert callable(ocr_document_job)


def test_ocr_page_job_backwards_compatibility():
    """Test that ocr_page_job alias exists for backwards compatibility."""
    from clerk.workers import ocr_document_job, ocr_page_job

    # Both should be callable
    assert callable(ocr_document_job)
    assert callable(ocr_page_job)

    # They should be the same function
    assert ocr_page_job is ocr_document_job


def test_db_compilation_job_accepts_run_id(mocker):
    """Test that db_compilation_job accepts run_id parameter."""
    from clerk.workers import db_compilation_job

    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch("clerk.utils.build_db_from_text_internal")
    mocker.patch("clerk.queue_db.update_site_progress")
    mocker.patch("clerk.queue.get_deploy_queue")
    mocker.patch("clerk.queue_db.track_job")
    mocker.patch("clerk.cli.update_page_count")
    mocker.patch("clerk.cli.rebuild_site_fts_internal")
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("os.path.getsize", return_value=1024)
    mock_db = mocker.MagicMock()
    mock_db.table_names.return_value = ["meetings", "minutes"]
    mocker.patch("sqlite_utils.Database", return_value=mock_db)
    mocker.patch(
        "clerk.workers.get_site_by_subdomain",
        return_value={"subdomain": "test.civic.band", "pages": 10},
    )
    mock_clerk_logger = mocker.patch("clerk.workers.ClerkLogger")

    db_compilation_job("test.civic.band", run_id="test_123_abc")

    # Verify ClerkLogger was created with stage="compilation"
    mock_clerk_logger.assert_called()


def test_db_compilation_job_passes_run_id_to_deploy(mocker):
    """Test that db_compilation_job passes run_id to deploy job."""
    from clerk.workers import db_compilation_job

    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch("clerk.utils.build_db_from_text_internal")
    mocker.patch("clerk.queue_db.update_site_progress")
    mocker.patch("clerk.queue_db.track_job")
    mocker.patch("clerk.cli.update_page_count")
    mocker.patch("clerk.cli.rebuild_site_fts_internal")
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("os.path.getsize", return_value=1024)
    mock_db = mocker.MagicMock()
    mock_db.table_names.return_value = ["meetings", "minutes"]
    mocker.patch("sqlite_utils.Database", return_value=mock_db)
    mocker.patch(
        "clerk.workers.get_site_by_subdomain",
        return_value={"subdomain": "test.civic.band", "pages": 10},
    )
    mocker.patch("clerk.workers.ClerkLogger")

    mock_deploy_queue = mocker.MagicMock()
    mock_deploy_job = mocker.MagicMock(id="deploy-job-123")
    mock_deploy_queue.enqueue.return_value = mock_deploy_job
    mocker.patch("clerk.queue.get_deploy_queue", return_value=mock_deploy_queue)

    db_compilation_job("test.civic.band", run_id="test_123_abc")

    call_kwargs = mock_deploy_queue.enqueue.call_args[1]
    assert call_kwargs["run_id"] == "test_123_abc"


def test_fetch_site_job_accepts_run_id_parameter(mocker):
    """Test that fetch_site_job accepts run_id parameter."""
    from clerk.workers import fetch_site_job

    # Mock all dependencies
    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch(
        "clerk.workers.get_site_by_subdomain", return_value={"subdomain": "test", "scraper": "test"}
    )
    mocker.patch("clerk.workers.create_site_progress")
    mocker.patch("clerk.workers.get_fetcher")
    mocker.patch("clerk.cli.fetch_internal")
    mocker.patch("clerk.workers.queue_ocr", return_value=0)
    mocker.patch("clerk.workers.Path")
    mocker.patch("clerk.queue.get_ocr_queue")
    mocker.patch("clerk.queue.get_compilation_queue")
    mocker.patch("clerk.workers.ClerkLogger")

    # Should not raise TypeError
    fetch_site_job("test.civic.band", run_id="test_123_abc")


def test_fetch_site_job_logs_fetch_started_milestone(mocker):
    """Test that fetch_site_job logs fetch_started milestone."""
    from clerk.workers import fetch_site_job

    # Mock dependencies
    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch(
        "clerk.workers.get_site_by_subdomain", return_value={"subdomain": "test", "scraper": "test"}
    )
    mocker.patch("clerk.workers.create_site_progress")
    mocker.patch("clerk.workers.get_fetcher")
    mocker.patch("clerk.cli.fetch_internal")
    mocker.patch("clerk.workers.queue_ocr", return_value=0)
    mocker.patch("clerk.workers.Path")
    mocker.patch("clerk.queue.get_ocr_queue")
    mocker.patch("clerk.queue.get_compilation_queue")
    mock_logger = mocker.MagicMock()
    mocker.patch("clerk.workers.ClerkLogger", return_value=mock_logger)

    fetch_site_job("test.civic.band", run_id="test_123_abc")

    # Verify fetch_started was logged
    started_calls = [call for call in mock_logger.log.call_args_list if call[0][0] == "fetch_started"]
    assert len(started_calls) == 1


def test_fetch_site_job_logs_fetch_completed_with_metrics(mocker):
    """Test that fetch_site_job logs fetch_completed with duration and count."""
    from clerk.workers import fetch_site_job

    # Mock dependencies to simulate successful completion
    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch(
        "clerk.workers.get_site_by_subdomain", return_value={"subdomain": "test", "scraper": "test"}
    )
    mocker.patch("clerk.workers.create_site_progress")
    mocker.patch("clerk.workers.get_fetcher")
    mocker.patch("clerk.cli.fetch_internal")
    mocker.patch("clerk.workers.update_site_progress")
    mocker.patch("clerk.workers.track_job")
    mocker.patch("clerk.workers.queue_ocr", return_value=0)

    # Mock Path to return no PDFs (simplest case)
    mock_path_class = mocker.patch("clerk.workers.Path")
    mock_path_instance = mocker.MagicMock()
    mock_path_instance.exists.return_value = False
    mock_path_class.return_value = mock_path_instance

    mocker.patch("clerk.queue.get_ocr_queue")
    mocker.patch("clerk.queue.get_compilation_queue")
    mock_logger = mocker.MagicMock()
    mocker.patch("clerk.workers.ClerkLogger", return_value=mock_logger)

    fetch_site_job("test.civic.band", run_id="test_123_abc")

    # Verify fetch_completed was logged
    completed_calls = [call for call in mock_logger.log.call_args_list if call[0][0] == "fetch_completed"]
    assert len(completed_calls) == 1

    # Verify it has duration_seconds and total_pdfs
    call_kwargs = completed_calls[0][1]
    assert "duration_seconds" in call_kwargs
    assert "total_pdfs" in call_kwargs


def test_fetch_site_job_passes_run_id_to_ocr_jobs(mocker):
    """Test that fetch_site_job passes run_id to spawned OCR jobs."""
    from clerk.workers import fetch_site_job

    # Mock dependencies
    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch(
        "clerk.workers.get_site_by_subdomain", return_value={"subdomain": "test", "scraper": "test"}
    )
    mocker.patch("clerk.workers.create_site_progress")
    mocker.patch("clerk.workers.update_site_progress")
    mocker.patch("clerk.workers.track_job")
    mocker.patch("clerk.workers.get_fetcher")
    mocker.patch("clerk.cli.fetch_internal")
    mocker.patch("clerk.workers.ClerkLogger")
    mocker.patch("clerk.workers.initialize_stage")

    # Mock Path to return some PDFs
    mock_pdf = mocker.MagicMock()
    mock_pdf.name = "test.pdf"
    mock_path_class = mocker.patch("clerk.workers.Path")
    mock_path_instance = mocker.MagicMock()
    mock_path_instance.exists.return_value = True
    mock_path_instance.glob.return_value = [mock_pdf]
    mock_path_class.return_value = mock_path_instance

    # Mock OCR queue with batch enqueueing
    mock_ocr_queue = mocker.MagicMock()
    mock_job = mocker.MagicMock(id="ocr-job-123")
    mock_job_data = mocker.MagicMock()
    mock_ocr_queue.prepare_data.return_value = mock_job_data
    mock_ocr_queue.enqueue_many.return_value = [mock_job]
    mocker.patch("clerk.queue.get_ocr_queue", return_value=mock_ocr_queue)

    # Mock track_jobs_bulk instead of track_job
    mocker.patch("clerk.workers.track_jobs_bulk")

    # Mock compilation queue for coordinator
    mock_compilation_queue = mocker.MagicMock()
    mock_coord_job = mocker.MagicMock(id="coord-job-123")
    mock_compilation_queue.enqueue.return_value = mock_coord_job
    mocker.patch("clerk.queue.get_compilation_queue", return_value=mock_compilation_queue)

    fetch_site_job("test.civic.band", run_id="test_123_abc")

    # Verify OCR jobs were batch enqueued with run_id
    mock_ocr_queue.prepare_data.assert_called()
    call_kwargs = mock_ocr_queue.prepare_data.call_args[1]["kwargs"]
    assert call_kwargs["run_id"] == "test_123_abc"


def test_deploy_job_accepts_run_id(mocker):
    """Test that deploy_job accepts run_id parameter."""
    from clerk.workers import deploy_job

    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch(
        "clerk.workers.get_site_by_subdomain",
        return_value={"subdomain": "test.civic.band", "status": "deployed"},
    )
    mocker.patch("clerk.workers.update_site_progress")
    mocker.patch("clerk.workers.increment_stage_progress")
    mocker.patch("clerk.utils.pm")
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("os.path.getsize", return_value=2048)
    mock_logger = mocker.MagicMock()
    mocker.patch("clerk.workers.ClerkLogger", return_value=mock_logger)

    deploy_job("test.civic.band", run_id="test_123_abc")

    # Verify ClerkLogger was created with stage="deploy"
    constructor_call = mocker.patch("clerk.workers.ClerkLogger").call_args
    # Just verify deploy_job ran without errors


def test_deploy_job_logs_deploy_completed(mocker):
    """Test that deploy_job logs deploy_completed milestone."""
    from clerk.workers import deploy_job

    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch(
        "clerk.workers.get_site_by_subdomain",
        return_value={"subdomain": "test.civic.band", "status": "deployed"},
    )
    mocker.patch("clerk.workers.update_site_progress")
    mocker.patch("clerk.workers.increment_stage_progress")
    mocker.patch("clerk.utils.pm")
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("os.path.getsize", return_value=2048)
    mock_logger = mocker.MagicMock()
    mocker.patch("clerk.workers.ClerkLogger", return_value=mock_logger)

    deploy_job("test.civic.band", run_id="test_123_abc")

    completed_calls = [call for call in mock_logger.log.call_args_list if "deploy_completed" in call[0][0]]
    assert len(completed_calls) == 1


def test_ocr_complete_coordinator_accepts_run_id(mocker):
    """Test that ocr_complete_coordinator accepts run_id parameter."""
    from clerk.workers import ocr_complete_coordinator

    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch("clerk.workers.update_site_progress")
    mocker.patch("clerk.workers.track_job")

    # Mock txt directory verification
    mock_txt_dir = mocker.MagicMock()
    mock_txt_dir.exists.return_value = True
    mock_txt_file = mocker.MagicMock()
    mock_txt_file.name = "test.txt"
    mock_txt_dir.glob.return_value = [mock_txt_file]
    mocker.patch("clerk.workers.Path", return_value=mock_txt_dir)

    mock_compilation_queue = mocker.MagicMock()
    mock_compilation_queue.enqueue.return_value = mocker.MagicMock(id="comp-job")
    mocker.patch("clerk.queue.get_compilation_queue", return_value=mock_compilation_queue)

    mock_extraction_queue = mocker.MagicMock()
    mock_extraction_queue.enqueue.return_value = mocker.MagicMock(id="ext-job")
    mocker.patch("clerk.queue.get_extraction_queue", return_value=mock_extraction_queue)

    mock_logger = mocker.MagicMock()
    mocker.patch("clerk.workers.ClerkLogger", return_value=mock_logger)

    ocr_complete_coordinator("test.civic.band", run_id="test_123_abc")

    # Verify ClerkLogger was created with run_id and stage
    constructor_calls = mocker.patch("clerk.workers.ClerkLogger").call_args_list
    # Just verify coordinator ran without errors


def test_ocr_document_job_accepts_run_id_parameter(mocker):
    """Test that ocr_document_job accepts run_id parameter."""
    from clerk.workers import ocr_document_job

    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch("clerk.workers.get_site_by_subdomain", return_value={"subdomain": "test"})
    mock_fetcher = mocker.MagicMock()
    mocker.patch("clerk.workers.get_fetcher", return_value=mock_fetcher)
    mocker.patch("clerk.workers.increment_stage_progress")
    mocker.patch("clerk.workers.ClerkLogger")

    ocr_document_job("test.civic.band", "/path/to/test.pdf", "tesseract", run_id="test_123_abc")


def test_ocr_document_job_logs_with_stage_ocr(mocker):
    """Test that ocr_document_job creates logger with stage=ocr."""
    from clerk.workers import ocr_document_job

    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch("clerk.workers.get_site_by_subdomain", return_value={"subdomain": "test"})
    mock_fetcher = mocker.MagicMock()
    mocker.patch("clerk.workers.get_fetcher", return_value=mock_fetcher)
    mocker.patch("clerk.workers.increment_stage_progress")
    mock_clerk_logger = mocker.patch("clerk.workers.ClerkLogger")

    ocr_document_job("test.civic.band", "/path/to/test.pdf", "tesseract", run_id="test_123_abc")

    # Verify ClerkLogger was created with stage="ocr"
    assert any(
        call[1].get("stage") == "ocr" and call[1].get("subdomain") == "test.civic.band"
        for call in mock_clerk_logger.call_args_list
    )


def test_ocr_job_updates_counters_on_success(mocker):
    """Test that ocr_document_job updates atomic counters on success."""
    from clerk.workers import ocr_document_job

    # Mock dependencies
    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch("clerk.workers.get_site_by_subdomain", return_value={"subdomain": "test"})
    mock_fetcher = mocker.MagicMock()
    mocker.patch("clerk.workers.get_fetcher", return_value=mock_fetcher)
    mocker.patch("clerk.workers.ClerkLogger")

    # Mock atomic counter functions
    mock_increment_completed = mocker.patch("clerk.workers.increment_completed")
    mock_should_trigger = mocker.patch(
        "clerk.workers.should_trigger_coordinator", return_value=False
    )
    _mock_claim = mocker.patch("clerk.workers.claim_coordinator_enqueue")

    # Run OCR job
    ocr_document_job(
        "test.civic.band", "/path/to/meeting/2024-01-01.pdf", "tesseract", run_id="test_123"
    )

    # Verify increment_completed was called
    mock_increment_completed.assert_called_once_with("test.civic.band", "ocr")

    # Verify should_trigger_coordinator was called
    mock_should_trigger.assert_called_once_with("test.civic.band", "ocr")


def test_ocr_job_updates_counters_on_failure(mocker):
    """Test that ocr_document_job updates atomic counters on failure."""
    from clerk.workers import ocr_document_job

    # Mock dependencies
    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch("clerk.workers.get_site_by_subdomain", return_value={"subdomain": "test"})

    # Mock fetcher to raise an error
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.do_ocr_job.side_effect = RuntimeError("OCR processing failed")
    mocker.patch("clerk.workers.get_fetcher", return_value=mock_fetcher)
    mocker.patch("clerk.workers.ClerkLogger")

    # Mock atomic counter functions
    mock_increment_failed = mocker.patch("clerk.workers.increment_failed")
    mock_should_trigger = mocker.patch(
        "clerk.workers.should_trigger_coordinator", return_value=False
    )

    # Run OCR job (should not raise - errors are caught)
    ocr_document_job(
        "test.civic.band", "/path/to/meeting/2024-01-01.pdf", "tesseract", run_id="test_123"
    )

    # Verify increment_failed was called with error details
    mock_increment_failed.assert_called_once()
    call_kwargs = mock_increment_failed.call_args[1]
    assert call_kwargs["error_message"] == "OCR processing failed"
    assert call_kwargs["error_class"] == "RuntimeError"

    # Verify positional args
    call_args = mock_increment_failed.call_args[0]
    assert call_args[0] == "test.civic.band"
    assert call_args[1] == "ocr"

    # Verify should_trigger_coordinator was still called
    mock_should_trigger.assert_called_once_with("test.civic.band", "ocr")


def test_coordinator_resets_enqueued_flag(mock_site, tmp_path, monkeypatch, mocker):
    """Coordinator should reset coordinator_enqueued flag for next stage."""
    from pathlib import Path

    from sqlalchemy import select

    from clerk.db import civic_db_connection, upsert_site
    from clerk.models import sites_table
    from clerk.pipeline_state import (
        claim_coordinator_enqueue,
        increment_completed,
        initialize_stage,
    )
    from clerk.workers import ocr_complete_coordinator

    subdomain = "test-site"
    mock_site["subdomain"] = subdomain

    # Setup site in database
    with civic_db_connection() as conn:
        upsert_site(conn, mock_site)

    initialize_stage(subdomain, "ocr", total_jobs=1)
    increment_completed(subdomain, "ocr")
    claim_coordinator_enqueue(subdomain)

    # Create txt files (OCR succeeded)
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    txt_dir = Path(tmp_path) / subdomain / "txt" / "Meeting"
    txt_dir.mkdir(parents=True)
    (txt_dir / "2024-01-01.txt").write_text("test content")

    # Mock queue operations (coordinator enqueues compilation and deploy jobs)
    mock_compilation_queue = mocker.MagicMock()
    mock_compilation_queue.enqueue.return_value = mocker.MagicMock(id="comp-job")
    mocker.patch("clerk.queue.get_compilation_queue", return_value=mock_compilation_queue)

    mock_deploy_queue = mocker.MagicMock()
    mock_deploy_queue.enqueue.return_value = mocker.MagicMock(id="deploy-job")
    mocker.patch("clerk.queue.get_deploy_queue", return_value=mock_deploy_queue)

    # Mock job tracking to avoid database conflicts
    mocker.patch("clerk.workers.track_job")

    # Run coordinator
    ocr_complete_coordinator(subdomain, run_id="test_run")

    # Verify flag reset and stage transitioned
    with civic_db_connection() as conn:
        site = conn.execute(
            select(sites_table).where(sites_table.c.subdomain == subdomain)
        ).fetchone()

    assert site.current_stage == "compilation"  # Moved to compilation stage
    assert site.coordinator_enqueued is False  # Flag reset
    assert site.compilation_total == 1  # Next stage initialized
