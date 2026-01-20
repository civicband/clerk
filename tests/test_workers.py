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
    mocker.patch("clerk.workers.get_current_job", return_value=mock_job)

    # Mock output_log
    mock_output_log = mocker.patch("clerk.workers.output_log")

    log_with_context(
        "test message", subdomain="test.civic.band", run_id="test_123_abc", stage="fetch"
    )

    # Verify output_log was called with job context
    mock_output_log.assert_called_once_with(
        "test message",
        subdomain="test.civic.band",
        run_id="test_123_abc",
        stage="fetch",
        job_id="job-123",
        parent_job_id="job-456",
    )


def test_log_with_context_handles_no_job(mocker):
    """Test that log_with_context works when no RQ job context exists."""
    from clerk.workers import log_with_context

    # Mock get_current_job to return None (no job context)
    mocker.patch("clerk.workers.get_current_job", return_value=None)

    # Mock output_log
    mock_output_log = mocker.patch("clerk.workers.output_log")

    log_with_context(
        "test message", subdomain="test.civic.band", run_id="test_123_abc", stage="fetch"
    )

    # Verify output_log was called with None for job fields
    mock_output_log.assert_called_once_with(
        "test message",
        subdomain="test.civic.band",
        run_id="test_123_abc",
        stage="fetch",
        job_id=None,
        parent_job_id=None,
    )


def test_log_with_context_passes_extra_kwargs(mocker):
    """Test that log_with_context passes through additional kwargs."""
    from clerk.workers import log_with_context

    mocker.patch("clerk.workers.get_current_job", return_value=None)
    mock_output_log = mocker.patch("clerk.workers.output_log")

    log_with_context(
        "test message",
        subdomain="test.civic.band",
        run_id="test_123_abc",
        stage="fetch",
        total_pdfs=47,
        duration_seconds=120.5,
    )

    # Verify extra kwargs were passed through
    call_kwargs = mock_output_log.call_args[1]
    assert call_kwargs["total_pdfs"] == 47
    assert call_kwargs["duration_seconds"] == 120.5


def test_db_compilation_job_accepts_run_id(mocker):
    """Test that db_compilation_job accepts run_id parameter."""
    from clerk.workers import db_compilation_job

    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch("clerk.utils.build_db_from_text_internal")
    mocker.patch("clerk.queue_db.update_site_progress")
    mocker.patch("clerk.queue.get_deploy_queue")
    mocker.patch("clerk.queue_db.track_job")
    mocker.patch("clerk.cli.update_page_count")  # Mock new call
    mocker.patch("clerk.cli.rebuild_site_fts_internal")  # Mock new call
    mocker.patch("os.path.exists", return_value=True)  # Mock meetings.db exists
    mocker.patch("os.path.getsize", return_value=1024)  # Mock db size
    mock_db = mocker.MagicMock()
    mock_db.table_names.return_value = ["meetings", "minutes"]  # Mock tables exist
    mocker.patch("sqlite_utils.Database", return_value=mock_db)
    mocker.patch(
        "clerk.workers.get_site_by_subdomain",
        return_value={"subdomain": "test.civic.band", "pages": 10},
    )
    mock_log = mocker.patch("clerk.workers.log_with_context")

    db_compilation_job("test.civic.band", run_id="test_123_abc", extract_entities=False)

    assert any(call[1]["stage"] == "compilation" for call in mock_log.call_args_list)


def test_db_compilation_job_passes_run_id_to_deploy(mocker):
    """Test that db_compilation_job passes run_id to deploy job."""
    from clerk.workers import db_compilation_job

    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch("clerk.utils.build_db_from_text_internal")
    mocker.patch("clerk.queue_db.update_site_progress")
    mocker.patch("clerk.queue_db.track_job")
    mocker.patch("clerk.cli.update_page_count")  # Mock new call
    mocker.patch("clerk.cli.rebuild_site_fts_internal")  # Mock new call
    mocker.patch("os.path.exists", return_value=True)  # Mock meetings.db exists
    mocker.patch("os.path.getsize", return_value=1024)  # Mock db size
    mock_db = mocker.MagicMock()
    mock_db.table_names.return_value = ["meetings", "minutes"]  # Mock tables exist
    mocker.patch("sqlite_utils.Database", return_value=mock_db)
    mocker.patch(
        "clerk.workers.get_site_by_subdomain",
        return_value={"subdomain": "test.civic.band", "pages": 10},
    )
    mocker.patch("clerk.workers.log_with_context")

    mock_deploy_queue = mocker.MagicMock()
    mock_deploy_job = mocker.MagicMock(id="deploy-job-123")
    mock_deploy_queue.enqueue.return_value = mock_deploy_job
    mocker.patch("clerk.queue.get_deploy_queue", return_value=mock_deploy_queue)

    db_compilation_job("test.civic.band", run_id="test_123_abc", extract_entities=False)

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
    mocker.patch("clerk.cli.get_fetcher")
    mocker.patch("clerk.cli.fetch_internal")
    mocker.patch("clerk.workers.Path")
    mocker.patch("clerk.queue.get_ocr_queue")
    mocker.patch("clerk.queue.get_compilation_queue")
    mock_log = mocker.patch("clerk.workers.log_with_context")

    # Should not raise TypeError
    fetch_site_job("test.civic.band", run_id="test_123_abc")

    # Verify log_with_context was called with run_id
    assert any(call[1]["run_id"] == "test_123_abc" for call in mock_log.call_args_list)


def test_fetch_site_job_logs_fetch_started_milestone(mocker):
    """Test that fetch_site_job logs fetch_started milestone."""
    from clerk.workers import fetch_site_job

    # Mock dependencies
    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch(
        "clerk.workers.get_site_by_subdomain", return_value={"subdomain": "test", "scraper": "test"}
    )
    mocker.patch("clerk.workers.create_site_progress")
    mocker.patch("clerk.cli.get_fetcher")
    mocker.patch("clerk.cli.fetch_internal")
    mocker.patch("clerk.workers.Path")
    mocker.patch("clerk.queue.get_ocr_queue")
    mocker.patch("clerk.queue.get_compilation_queue")
    mock_log = mocker.patch("clerk.workers.log_with_context")

    fetch_site_job("test.civic.band", run_id="test_123_abc")

    # Verify fetch_started was logged
    started_calls = [call for call in mock_log.call_args_list if call[0][0] == "fetch_started"]
    assert len(started_calls) == 1

    # Verify it has stage="fetch"
    assert started_calls[0][1]["stage"] == "fetch"


def test_fetch_site_job_logs_fetch_completed_with_metrics(mocker):
    """Test that fetch_site_job logs fetch_completed with duration and count."""
    from clerk.workers import fetch_site_job

    # Mock dependencies to simulate successful completion
    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch(
        "clerk.workers.get_site_by_subdomain", return_value={"subdomain": "test", "scraper": "test"}
    )
    mocker.patch("clerk.workers.create_site_progress")
    mocker.patch("clerk.cli.get_fetcher")
    mocker.patch("clerk.cli.fetch_internal")
    mocker.patch("clerk.workers.update_site_progress")
    mocker.patch("clerk.workers.track_job")

    # Mock Path to return no PDFs (simplest case)
    mock_path_class = mocker.patch("clerk.workers.Path")
    mock_path_instance = mocker.MagicMock()
    mock_path_instance.exists.return_value = False
    mock_path_class.return_value = mock_path_instance

    mocker.patch("clerk.queue.get_ocr_queue")
    mocker.patch("clerk.queue.get_compilation_queue")
    mock_log = mocker.patch("clerk.workers.log_with_context")

    fetch_site_job("test.civic.band", run_id="test_123_abc")

    # Verify fetch_completed was logged
    completed_calls = [call for call in mock_log.call_args_list if call[0][0] == "fetch_completed"]
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
    mocker.patch("clerk.cli.get_fetcher")
    mocker.patch("clerk.cli.fetch_internal")
    mocker.patch("clerk.workers.log_with_context")

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
    mocker.patch("os.path.exists", return_value=True)  # Mock sites.db exists
    mocker.patch("os.path.getsize", return_value=2048)  # Mock sites.db size
    mock_log = mocker.patch("clerk.workers.log_with_context")

    deploy_job("test.civic.band", run_id="test_123_abc")

    assert any(call[1]["stage"] == "deploy" for call in mock_log.call_args_list)


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
    mocker.patch("os.path.exists", return_value=True)  # Mock sites.db exists
    mocker.patch("os.path.getsize", return_value=2048)  # Mock sites.db size
    mock_log = mocker.patch("clerk.workers.log_with_context")

    deploy_job("test.civic.band", run_id="test_123_abc")

    completed_calls = [call for call in mock_log.call_args_list if "deploy_completed" in call[0][0]]
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

    mock_log = mocker.patch("clerk.workers.log_with_context")

    ocr_complete_coordinator("test.civic.band", run_id="test_123_abc")

    assert any(
        call[1]["run_id"] == "test_123_abc" and call[1]["stage"] == "ocr"
        for call in mock_log.call_args_list
    )


# def test_ocr_complete_coordinator_passes_run_id_to_child_jobs(mocker):
#     """Test that coordinator passes run_id to compilation and extraction jobs."""
#     from clerk.workers import ocr_complete_coordinator

#     mocker.patch("clerk.workers.civic_db_connection")
#     mocker.patch("clerk.workers.update_site_progress")
#     mocker.patch("clerk.workers.track_job")
#     mocker.patch("clerk.workers.log_with_context")

#     # Mock txt directory verification
#     mock_txt_dir = mocker.MagicMock()
#     mock_txt_dir.exists.return_value = True
#     mock_txt_file = mocker.MagicMock()
#     mock_txt_file.name = "test.txt"
#     mock_txt_dir.glob.return_value = [mock_txt_file]
#     mocker.patch("clerk.workers.Path", return_value=mock_txt_dir)

#     mock_compilation_queue = mocker.MagicMock()
#     mock_compilation_job = mocker.MagicMock(id="comp-job-123")
#     mock_compilation_queue.enqueue.return_value = mock_compilation_job
#     mocker.patch("clerk.queue.get_compilation_queue", return_value=mock_compilation_queue)

#     mock_extraction_queue = mocker.MagicMock()
#     mock_extraction_job = mocker.MagicMock(id="ext-job-123")
#     mock_extraction_queue.enqueue.return_value = mock_extraction_job
#     mocker.patch("clerk.queue.get_extraction_queue", return_value=mock_extraction_queue)

#     ocr_complete_coordinator("test.civic.band", run_id="test_123_abc")

#     comp_call_kwargs = mock_compilation_queue.enqueue.call_args[1]
#     assert comp_call_kwargs["run_id"] == "test_123_abc"

#     ext_call_kwargs = mock_extraction_queue.enqueue.call_args[1]
#     assert ext_call_kwargs["run_id"] == "test_123_abc"


def test_ocr_page_job_accepts_run_id_parameter(mocker):
    """Test that ocr_page_job accepts run_id parameter."""
    from clerk.workers import ocr_page_job

    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch("clerk.workers.get_site_by_subdomain", return_value={"subdomain": "test"})
    mock_fetcher = mocker.MagicMock()
    mocker.patch("clerk.cli.get_fetcher", return_value=mock_fetcher)
    mocker.patch("clerk.workers.increment_stage_progress")
    mock_log = mocker.patch("clerk.workers.log_with_context")

    ocr_page_job("test.civic.band", "/path/to/test.pdf", "tesseract", run_id="test_123_abc")

    assert any(call[1]["run_id"] == "test_123_abc" for call in mock_log.call_args_list)


def test_ocr_page_job_logs_with_stage_ocr(mocker):
    """Test that ocr_page_job logs with stage=ocr."""
    from clerk.workers import ocr_page_job

    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch("clerk.workers.get_site_by_subdomain", return_value={"subdomain": "test"})
    mock_fetcher = mocker.MagicMock()
    mocker.patch("clerk.cli.get_fetcher", return_value=mock_fetcher)
    mocker.patch("clerk.workers.increment_stage_progress")
    mock_log = mocker.patch("clerk.workers.log_with_context")

    ocr_page_job("test.civic.band", "/path/to/test.pdf", "tesseract", run_id="test_123_abc")

    assert any(call[1].get("stage") == "ocr" for call in mock_log.call_args_list)


def test_extraction_job_accepts_run_id(mocker):
    """Test that extraction_job accepts run_id parameter."""
    from clerk.workers import extraction_job

    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch("clerk.cli.extract_entities_internal")
    mocker.patch("clerk.workers.update_site_progress")
    mocker.patch("clerk.workers.track_job")

    # Mock Path to return no text files
    mock_path_class = mocker.patch("clerk.workers.Path")
    mock_path_instance = mocker.MagicMock()
    mock_path_instance.exists.return_value = False
    mock_path_class.return_value = mock_path_instance

    # Mock compilation queue
    mock_compilation_queue = mocker.MagicMock()
    mock_job = mocker.MagicMock(id="comp-job-123")
    mock_compilation_queue.enqueue.return_value = mock_job
    mocker.patch("clerk.queue.get_compilation_queue", return_value=mock_compilation_queue)

    mock_log = mocker.patch("clerk.workers.log_with_context")

    extraction_job("test.civic.band", run_id="test_123_abc")

    assert any(call[1]["stage"] == "extraction" for call in mock_log.call_args_list)


def test_extraction_job_logs_extraction_started(mocker):
    """Test that extraction_job logs extraction_started milestone."""
    from clerk.workers import extraction_job

    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch("clerk.cli.extract_entities_internal")
    mocker.patch("clerk.workers.update_site_progress")
    mocker.patch("clerk.workers.track_job")

    # Mock Path to return no text files
    mock_path_class = mocker.patch("clerk.workers.Path")
    mock_path_instance = mocker.MagicMock()
    mock_path_instance.exists.return_value = False
    mock_path_class.return_value = mock_path_instance

    # Mock compilation queue
    mock_compilation_queue = mocker.MagicMock()
    mock_job = mocker.MagicMock(id="comp-job-123")
    mock_compilation_queue.enqueue.return_value = mock_job
    mocker.patch("clerk.queue.get_compilation_queue", return_value=mock_compilation_queue)

    mock_log = mocker.patch("clerk.workers.log_with_context")

    extraction_job("test.civic.band", run_id="test_123_abc")

    started_calls = [call for call in mock_log.call_args_list if "extraction_started" in call[0][0]]
    assert len(started_calls) >= 1


def test_ocr_job_updates_counters_on_success(mocker):
    """Test that ocr_page_job updates atomic counters on success."""
    from clerk.workers import ocr_page_job

    # Mock dependencies
    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch("clerk.workers.get_site_by_subdomain", return_value={"subdomain": "test"})
    mock_fetcher = mocker.MagicMock()
    mocker.patch("clerk.cli.get_fetcher", return_value=mock_fetcher)
    mocker.patch("clerk.workers.log_with_context")

    # Mock atomic counter functions
    mock_increment_completed = mocker.patch("clerk.workers.increment_completed")
    mock_should_trigger = mocker.patch(
        "clerk.workers.should_trigger_coordinator", return_value=False
    )
    _mock_claim = mocker.patch("clerk.workers.claim_coordinator_enqueue")

    # Run OCR job
    ocr_page_job(
        "test.civic.band", "/path/to/meeting/2024-01-01.pdf", "tesseract", run_id="test_123"
    )

    # Verify increment_completed was called
    mock_increment_completed.assert_called_once_with("test.civic.band", "ocr")

    # Verify should_trigger_coordinator was called
    mock_should_trigger.assert_called_once_with("test.civic.band", "ocr")


def test_ocr_job_updates_counters_on_failure(mocker):
    """Test that ocr_page_job updates atomic counters on failure."""
    from clerk.workers import ocr_page_job

    # Mock dependencies
    mocker.patch("clerk.workers.civic_db_connection")
    mocker.patch("clerk.workers.get_site_by_subdomain", return_value={"subdomain": "test"})

    # Mock fetcher to raise an error
    mock_fetcher = mocker.MagicMock()
    mock_fetcher.do_ocr_job.side_effect = RuntimeError("OCR processing failed")
    mocker.patch("clerk.cli.get_fetcher", return_value=mock_fetcher)
    mocker.patch("clerk.workers.log_with_context")

    # Mock atomic counter functions
    mock_increment_failed = mocker.patch("clerk.workers.increment_failed")
    mock_should_trigger = mocker.patch(
        "clerk.workers.should_trigger_coordinator", return_value=False
    )

    # Run OCR job (should not raise - errors are caught)
    ocr_page_job(
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

    # Mock queue operations (coordinator enqueues compilation, extraction and deploy jobs)
    mock_compilation_queue = mocker.MagicMock()
    mock_compilation_queue.enqueue.return_value = mocker.MagicMock(id="comp-job")
    mocker.patch("clerk.queue.get_compilation_queue", return_value=mock_compilation_queue)

    mock_extraction_queue = mocker.MagicMock()
    mock_extraction_queue.enqueue.return_value = mocker.MagicMock(id="ext-job")
    mocker.patch("clerk.queue.get_extraction_queue", return_value=mock_extraction_queue)

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

    assert site.current_stage == "extraction"  # Moved to next stage
    assert site.coordinator_enqueued is False  # Flag reset
    assert site.compilation_total == 1  # Next stage initialized
    assert site.extraction_total == 1
