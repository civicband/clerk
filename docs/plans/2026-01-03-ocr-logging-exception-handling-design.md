# OCR Logging and Exception Handling Design

**Date:** 2026-01-03

**Goal:** Implement comprehensive logging and exception handling for OCR processing to provide progress visibility, failure diagnosis, and performance monitoring.

---

## Problem Statement

Current OCR processing has:
- **Silent failures** - Jobs stop without indication of what failed or why
- **Partial visibility** - Error messages lack context (which page, document, or operation failed)
- **Lost work** - Can't determine what was completed vs. what needs reprocessing after failures
- **No progress tracking** - Long-running jobs provide no visibility into progress or ETA

---

## Architecture Overview

### Dual Output System

Build on existing `log()` wrapper in `clerk.output`:
1. **Human-readable progress** - Direct `click.echo(err=True)` for progress updates to stderr
2. **Structured logging** - Existing `log()` function already configured with JSON formatting and Loki handler

The `log()` function supports:
```python
log("message", subdomain=subdomain, level="error", extra_field=value)
```

### Three-Tier Progress Tracking

1. **Job Level** - Progress to stderr: "OCR Progress: 45/100 documents"
2. **Document Level** - Via `log()`: document being processed, index, total
3. **Operation Level** - Via `log()` with timing: each operation (PDF read, image conversion, OCR) with duration

### Hierarchical Error Handling

Errors are classified and handled appropriately:
- **Transient errors** → Retry decorator with 2s delay, max 3 attempts
- **Permanent errors** → Log with full context, append to JSONL manifest, continue processing
- **Critical errors** → Log at error level, raise exception, halt job

### Job State & Failure Manifest (JSONL)

**JobState** dataclass tracks runtime state:
- Total documents, completed, failed, skipped
- Current document being processed
- Start time, operation timings, ETA calculation

**Failure manifest** written as `{storage_dir}/{subdomain}/ocr_failures_{job_id}.jsonl`:
- **One JSON object per line** - each failure appended immediately
- **Atomic writes** - if job crashes, all failures up to crash point are preserved
- **No corruption** - incomplete final line can be detected and discarded

Example entries:
```jsonl
{"job_id":"ocr_20260103_143052","document_path":"pdfs/CityCouncil/2024-01-15.pdf","meeting":"CityCouncil","date":"2024-01-15","error_type":"permanent","error_class":"PdfReadError","error_message":"PDF is corrupted","failed_at":"2026-01-03T14:31:15Z","retry_count":3}
{"job_id":"ocr_20260103_143052","document_path":"pdfs/Planning/2024-02-20.pdf","meeting":"Planning","date":"2024-02-20","error_type":"transient","error_class":"HTTPTimeout","error_message":"Connection timeout","failed_at":"2026-01-03T14:35:22Z","retry_count":3}
```

**Benefits:**
- **Retry workflows** - Feed failed items back into OCR process
- **Failure analysis** - Identify patterns (which meetings/dates fail, error types)
- **Manual intervention** - Review and fix problematic PDFs
- **Survives crashes** - JSONL format ensures data up to crash point is preserved

---

## Implementation Details

### Structured Logging Patterns

**Job start/end:**
```python
log("OCR job started",
    subdomain=subdomain,
    job_id=job_id,
    total_documents=len(jobs),
    prefix=prefix)

log("OCR job completed",
    subdomain=subdomain,
    job_id=job_id,
    completed=state.completed,
    failed=state.failed,
    duration_seconds=elapsed)
```

**Document processing:**
```python
log("Processing document",
    subdomain=subdomain,
    job_id=job_id,
    meeting=meeting,
    date=date,
    document_index=idx,
    total_documents=total)
```

**Operation timing:**
```python
st = time.time()
# ... do operation ...
duration_ms = int((time.time() - st) * 1000)

log("Operation completed",
    subdomain=subdomain,
    operation="pdf_to_images",
    meeting=meeting,
    date=date,
    page_count=total_pages,
    duration_ms=duration_ms)
```

**Error logging:**
```python
log("Document failed",
    subdomain=subdomain,
    job_id=job_id,
    meeting=meeting,
    date=date,
    error_type="permanent",  # or "transient", "critical"
    error_class=exc.__class__.__name__,
    error_message=str(exc),
    retry_attempt=attempt,
    level="error")
```

**Key metadata fields:**
- `job_id` - unique per OCR run (format: `ocr_{timestamp}`)
- `subdomain` - already used throughout
- `meeting`, `date`, `document_path` - document context
- `document_index`, `total_documents` - progress tracking
- `operation`, `duration_ms` - performance metrics
- `error_type`, `error_class`, `retry_attempt` - error context

### Exception Handling & Retry Logic

**Error Classification:**

```python
# Transient - retry with backoff
TRANSIENT_ERRORS = (
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    OSError,  # Temporary file system issues
)

# Permanent - log and skip
PERMANENT_ERRORS = (
    PdfReadError,
    subprocess.CalledProcessError,  # Tesseract failures
    ParseError,
)

# Critical - fail fast
CRITICAL_ERRORS = (
    FileNotFoundError,  # Storage dir doesn't exist
    PermissionError,    # Can't write to storage
    ImportError,        # Missing dependencies
)
```

**Retry Decorator:**

```python
def retry_on_transient(max_attempts=3, delay_seconds=2):
    """Retry transient errors with fixed delay."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except TRANSIENT_ERRORS as e:
                    if attempt == max_attempts:
                        raise  # Exhausted retries
                    log(f"Transient error, retrying in {delay_seconds}s",
                        level="warning",
                        error_class=e.__class__.__name__,
                        error_message=str(e),
                        retry_attempt=attempt,
                        max_retries=max_attempts,
                        **kwargs.get('log_context', {}))
                    time.sleep(delay_seconds)
                except CRITICAL_ERRORS:
                    raise  # Fail fast
        return wrapper
    return decorator
```

**Failure Manifest Writer:**

```python
class FailureManifest:
    """Writes failure records to JSONL file with atomic appends."""

    def __init__(self, manifest_path):
        self.path = manifest_path
        self.file = open(manifest_path, 'a')  # Append mode

    def record_failure(self, job_id, document_path, meeting, date,
                       error_type, error_class, error_message, retry_count):
        entry = {
            "job_id": job_id,
            "document_path": document_path,
            "meeting": meeting,
            "date": date,
            "error_type": error_type,
            "error_class": error_class,
            "error_message": error_message,
            "failed_at": datetime.now().isoformat(),
            "retry_count": retry_count
        }
        self.file.write(json.dumps(entry) + '\n')
        self.file.flush()  # Ensure immediate write

    def close(self):
        self.file.close()
```

### Progress Tracking Implementation

**JobState Dataclass:**

```python
@dataclass
class JobState:
    job_id: str
    total_documents: int
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    start_time: float = field(default_factory=time.time)
    current_document: str | None = None

    def progress_pct(self) -> float:
        processed = self.completed + self.failed + self.skipped
        return (processed / self.total_documents * 100) if self.total_documents > 0 else 0

    def eta_seconds(self) -> float | None:
        processed = self.completed + self.failed + self.skipped
        if processed == 0:
            return None
        elapsed = time.time() - self.start_time
        rate = elapsed / processed
        remaining = self.total_documents - processed
        return rate * remaining
```

**Progress Output (stderr):**

```python
def print_progress(state: JobState):
    """Human-readable progress to stderr."""
    pct = state.progress_pct()
    processed = state.completed + state.failed + state.skipped
    eta = state.eta_seconds()
    eta_str = f"ETA: {int(eta)}s" if eta else "calculating..."

    click.echo(
        f"OCR Progress: [{processed}/{state.total_documents}] "
        f"{pct:.1f}% complete, {state.failed} failed | {eta_str}",
        err=True
    )
```

**Integration with do_ocr():**

```python
def do_ocr(self, prefix: str = "") -> None:
    job_id = f"ocr_{int(time.time())}"
    jobs = [(prefix, meeting, date) for meeting in ... for date in ...]

    state = JobState(job_id=job_id, total_documents=len(jobs))
    manifest = FailureManifest(f"{self.dir_prefix}/ocr_failures_{job_id}.jsonl")

    log("OCR job started", subdomain=self.subdomain, job_id=job_id,
        total_documents=len(jobs))

    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        future_to_job = {
            executor.submit(self.do_ocr_job, job, manifest, job_id, state): job
            for job in jobs
        }

        for future in concurrent.futures.as_completed(future_to_job):
            job = future_to_job[future]
            try:
                future.result()
                state.completed += 1
            except PERMANENT_ERRORS:
                state.failed += 1
            except CRITICAL_ERRORS:
                raise

            # Print progress every 5 documents
            if (state.completed + state.failed) % 5 == 0:
                print_progress(state)

    manifest.close()
    log("OCR job completed", subdomain=self.subdomain, job_id=job_id,
        completed=state.completed, failed=state.failed)
```

### Changes to do_ocr_job()

Add operation timing and retry logic:

```python
@retry_on_transient(max_attempts=3, delay_seconds=2)
def do_ocr_job(self, job: tuple[str, str, str], manifest: FailureManifest,
               job_id: str) -> None:
    st = time.time()
    prefix, meeting, date = job

    log("Processing document", subdomain=self.subdomain, job_id=job_id,
        meeting=meeting, date=date)

    try:
        doc_path = f"{self.dir_prefix}{prefix}/pdfs/{meeting}/{date}.pdf"

        # PDF reading with timing
        read_st = time.time()
        reader = PdfReader(doc_path)
        total_pages = len(reader.pages)
        log("PDF read", subdomain=self.subdomain, operation="pdf_read",
            meeting=meeting, date=date, page_count=total_pages,
            duration_ms=int((time.time() - read_st) * 1000))

        # Image conversion with timing
        conv_st = time.time()
        for chunk_start in range(1, total_pages + 1, PDF_CHUNK_SIZE):
            # ... existing conversion logic ...
        log("Image conversion", subdomain=self.subdomain,
            operation="pdf_to_images", meeting=meeting, date=date,
            duration_ms=int((time.time() - conv_st) * 1000))

        # OCR with timing
        ocr_st = time.time()
        for page_image in os.listdir(doc_image_dir_path):
            # ... existing OCR logic ...
        log("OCR completed", subdomain=self.subdomain, operation="tesseract",
            meeting=meeting, date=date, page_count=total_pages,
            duration_ms=int((time.time() - ocr_st) * 1000))

        # Cleanup
        os.remove(doc_path)
        shutil.rmtree(doc_image_dir_path)

        log("Document completed", subdomain=self.subdomain, job_id=job_id,
            meeting=meeting, date=date,
            total_duration_ms=int((time.time() - st) * 1000))

    except PERMANENT_ERRORS as e:
        manifest.record_failure(
            job_id=job_id,
            document_path=doc_path,
            meeting=meeting,
            date=date,
            error_type="permanent",
            error_class=e.__class__.__name__,
            error_message=str(e),
            retry_count=0  # Already retried by decorator if transient
        )
        log("Document failed", subdomain=self.subdomain, job_id=job_id,
            meeting=meeting, date=date, error_class=e.__class__.__name__,
            error_message=str(e), level="error")
        return  # Skip and continue

    except CRITICAL_ERRORS as e:
        log("Critical error", subdomain=self.subdomain, job_id=job_id,
            error_class=e.__class__.__name__, error_message=str(e),
            level="error")
        raise  # Fail fast
```

---

## Files to Create/Modify

### New Files

**src/clerk/ocr_utils.py** (~100 lines):
- `retry_on_transient()` decorator
- `FailureManifest` class
- `JobState` dataclass
- `print_progress()` function
- Error classification constants (`TRANSIENT_ERRORS`, `PERMANENT_ERRORS`, `CRITICAL_ERRORS`)

### Modified Files

**src/clerk/fetcher.py**:
- Import utilities from `ocr_utils`
- Update `do_ocr()` method to create JobState and FailureManifest, track progress
- Update `do_ocr_job()` method to add logging, timing, error handling
- Add operation-level timing for PDF read, image conversion, OCR

### Generated Files

**{storage_dir}/{subdomain}/ocr_failures_{job_id}.jsonl**:
- JSONL file with one failure record per line
- Created during OCR job execution
- Used for retry workflows and failure analysis

---

## Benefits

### Progress Visibility
- **Job-level**: See overall progress, completion percentage, ETA
- **Document-level**: Know which document is currently being processed
- **Operation-level**: Detailed timing metrics for performance analysis

### Failure Diagnosis
- **Full context**: Every error includes document, meeting, date, operation
- **Error classification**: Know if error is transient, permanent, or critical
- **Retry tracking**: See how many retries were attempted
- **Stack traces**: Available in structured logs for debugging

### Work Recovery
- **Failure manifest**: JSONL file survives crashes, lists all failed documents
- **Retry workflows**: Easy to reprocess just the failed items
- **Skip logic**: Permanent failures don't block entire job

### Performance Monitoring
- **Operation timing**: Measure PDF read, image conversion, OCR separately
- **Bottleneck identification**: Find slow operations via Loki queries
- **Historical trends**: Track performance over time in Grafana

---

## Loki Query Examples

**All OCR jobs:**
```
{job="clerk", command="ocr"}
```

**Failed documents:**
```
{job="clerk"} |= "Document failed"
```

**Slow operations (>30s):**
```
{job="clerk"} | json | duration_ms > 30000
```

**Job progress summary:**
```
{job="clerk"} |= "OCR job completed" | json
```

**Specific document failures:**
```
{job="clerk"} | json | meeting="CityCouncil" | level="error"
```
