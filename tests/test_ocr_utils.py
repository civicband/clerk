import httpx
import json
import subprocess
import tempfile
import time
from pathlib import Path
from xml.etree.ElementTree import ParseError

from clerk.ocr_utils import TRANSIENT_ERRORS, PERMANENT_ERRORS, CRITICAL_ERRORS, JobState, FailureManifest

# Import PdfReadError from the module we're testing to ensure we test the same class
try:
    from pypdf.errors import PdfReadError
except ImportError:
    from clerk.ocr_utils import PdfReadError


def test_transient_errors_tuple():
    """Transient errors should include network and temporary file issues."""
    assert httpx.ConnectTimeout in TRANSIENT_ERRORS
    assert httpx.ReadTimeout in TRANSIENT_ERRORS
    assert httpx.RemoteProtocolError in TRANSIENT_ERRORS
    assert OSError in TRANSIENT_ERRORS


def test_permanent_errors_tuple():
    """Permanent errors should include corrupted files and process failures."""
    assert PdfReadError in PERMANENT_ERRORS
    assert subprocess.CalledProcessError in PERMANENT_ERRORS
    assert ParseError in PERMANENT_ERRORS


def test_critical_errors_tuple():
    """Critical errors should include missing resources and permissions."""
    assert FileNotFoundError in CRITICAL_ERRORS
    assert PermissionError in CRITICAL_ERRORS
    assert ImportError in CRITICAL_ERRORS


def test_job_state_initialization():
    """JobState should initialize with job_id and total_documents."""
    state = JobState(job_id="test_123", total_documents=100)

    assert state.job_id == "test_123"
    assert state.total_documents == 100
    assert state.completed == 0
    assert state.failed == 0
    assert state.skipped == 0
    assert state.current_document is None
    assert isinstance(state.start_time, float)


def test_progress_pct_zero_completed():
    """Progress should be 0% when no documents processed."""
    state = JobState(job_id="test", total_documents=100)
    assert state.progress_pct() == 0.0


def test_progress_pct_partial():
    """Progress should calculate correctly with mixed results."""
    state = JobState(job_id="test", total_documents=100)
    state.completed = 40
    state.failed = 5
    state.skipped = 5

    assert state.progress_pct() == 50.0  # 50/100


def test_progress_pct_complete():
    """Progress should be 100% when all documents processed."""
    state = JobState(job_id="test", total_documents=100)
    state.completed = 90
    state.failed = 10

    assert state.progress_pct() == 100.0


def test_eta_seconds_no_progress():
    """ETA should be None when no documents processed."""
    state = JobState(job_id="test", total_documents=100)
    assert state.eta_seconds() is None


def test_eta_seconds_with_progress():
    """ETA should estimate time remaining based on current rate."""
    state = JobState(job_id="test", total_documents=100)
    state.start_time = time.time() - 10  # Started 10 seconds ago
    state.completed = 10  # Completed 10 documents

    eta = state.eta_seconds()

    # Should take ~90 seconds more (10 docs in 10s = 1 doc/s, 90 remaining)
    assert eta is not None
    assert 85 < eta < 95  # Allow some tolerance


def test_job_state_zero_total_documents():
    """JobState should handle zero total documents gracefully."""
    state = JobState(job_id="test", total_documents=0)
    assert state.progress_pct() == 0.0
    assert state.eta_seconds() is None


def test_failure_manifest_creates_file():
    """FailureManifest should create file in append mode."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manifest_path = Path(tmpdir) / "failures.jsonl"
        manifest = FailureManifest(str(manifest_path))
        manifest.close()

        assert manifest_path.exists()


def test_failure_manifest_record_failure():
    """FailureManifest should write JSONL entries."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manifest_path = Path(tmpdir) / "failures.jsonl"
        manifest = FailureManifest(str(manifest_path))

        manifest.record_failure(
            job_id="test_123",
            document_path="pdfs/Meeting/2024-01-01.pdf",
            meeting="Meeting",
            date="2024-01-01",
            error_type="permanent",
            error_class="PdfReadError",
            error_message="Corrupted PDF",
            retry_count=3
        )
        manifest.close()

        # Read and verify
        with open(manifest_path) as f:
            line = f.readline()
            entry = json.loads(line)

        assert entry["job_id"] == "test_123"
        assert entry["document_path"] == "pdfs/Meeting/2024-01-01.pdf"
        assert entry["meeting"] == "Meeting"
        assert entry["date"] == "2024-01-01"
        assert entry["error_type"] == "permanent"
        assert entry["error_class"] == "PdfReadError"
        assert entry["error_message"] == "Corrupted PDF"
        assert entry["retry_count"] == 3
        assert "failed_at" in entry


def test_failure_manifest_multiple_entries():
    """FailureManifest should write multiple JSONL entries."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manifest_path = Path(tmpdir) / "failures.jsonl"
        manifest = FailureManifest(str(manifest_path))

        manifest.record_failure(
            job_id="test",
            document_path="doc1.pdf",
            meeting="M1",
            date="2024-01-01",
            error_type="permanent",
            error_class="Error1",
            error_message="Error 1",
            retry_count=0
        )
        manifest.record_failure(
            job_id="test",
            document_path="doc2.pdf",
            meeting="M2",
            date="2024-01-02",
            error_type="transient",
            error_class="Error2",
            error_message="Error 2",
            retry_count=3
        )
        manifest.close()

        # Read and verify
        with open(manifest_path) as f:
            lines = f.readlines()

        assert len(lines) == 2
        entry1 = json.loads(lines[0])
        entry2 = json.loads(lines[1])
        assert entry1["document_path"] == "doc1.pdf"
        assert entry2["document_path"] == "doc2.pdf"


def test_failure_manifest_append_mode():
    """FailureManifest should append to existing file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manifest_path = Path(tmpdir) / "failures.jsonl"

        # First manifest writes one entry
        manifest1 = FailureManifest(str(manifest_path))
        manifest1.record_failure(
            job_id="test",
            document_path="doc1.pdf",
            meeting="M",
            date="2024-01-01",
            error_type="permanent",
            error_class="E",
            error_message="E",
            retry_count=0
        )
        manifest1.close()

        # Second manifest appends another entry
        manifest2 = FailureManifest(str(manifest_path))
        manifest2.record_failure(
            job_id="test",
            document_path="doc2.pdf",
            meeting="M",
            date="2024-01-02",
            error_type="permanent",
            error_class="E",
            error_message="E",
            retry_count=0
        )
        manifest2.close()

        # Verify both entries exist
        with open(manifest_path) as f:
            lines = f.readlines()
        assert len(lines) == 2
