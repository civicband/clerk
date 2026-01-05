# OCR Logging and Exception Handling

## Overview

The OCR pipeline provides comprehensive logging, exception handling, and progress tracking for long-running document processing jobs.

## Features

### Progress Tracking

Three levels of progress visibility:

1. **Job Level** - Overall progress printed to stderr every 5 documents:
   ```
   OCR Progress: [45/100] 45.0% complete, 2 failed | ETA: 120s
   ```

2. **Document Level** - Each document logged with context:
   ```json
   {"message": "Processing document", "job_id": "ocr_1234567890", "meeting": "CityCouncil", "date": "2024-01-15"}
   ```

3. **Operation Level** - Timing for each operation (PDF read, image conversion, OCR):
   ```json
   {"message": "PDF read", "operation": "pdf_read", "page_count": 25, "duration_ms": 1450}
   ```

### Error Handling

Errors are classified and handled appropriately:

**Transient Errors** (retry up to 3 times with 2s delay):
- Network timeouts (ConnectTimeout, ReadTimeout)
- Temporary file system issues (BlockingIOError, ChildProcessError, InterruptedError)

**Permanent Errors** (log, record in manifest, skip):
- Corrupted PDFs (PdfReadError)
- Tesseract failures (CalledProcessError)
- Parse errors (ParseError)

**Critical Errors** (fail fast):
- Missing storage directory (FileNotFoundError)
- Permission issues (PermissionError)
- Missing dependencies (ImportError)

### Failure Manifest

Failed documents are recorded in a JSONL file: `{storage_dir}/{subdomain}/ocr_failures_{job_id}.jsonl`

Example entry:
```json
{
  "job_id": "ocr_1234567890",
  "document_path": "pdfs/CityCouncil/2024-01-15.pdf",
  "meeting": "CityCouncil",
  "date": "2024-01-15",
  "error_type": "permanent",
  "error_class": "PdfReadError",
  "error_message": "PDF is corrupted or encrypted",
  "failed_at": "2024-01-15T14:30:45.123456",
  "retry_count": 3
}
```

## Usage

### Running OCR

```bash
uv run clerk ocr --subdomain=example.ca.civic.band
```

Progress will be printed to stderr, structured logs to stdout (and Loki if configured).

### Viewing Failed Documents

```bash
# List all failures
cat ../sites/example.ca.civic.band/ocr_failures_*.jsonl | jq .

# Group by error type
cat ../sites/example.ca.civic.band/ocr_failures_*.jsonl | jq -r .error_class | sort | uniq -c

# Get paths of failed documents
cat ../sites/example.ca.civic.band/ocr_failures_*.jsonl | jq -r .document_path
```

### Querying Logs in Loki

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

**Specific meeting failures:**
```
{job="clerk"} | json | meeting="CityCouncil" | level="error"
```

## Implementation Details

See `src/clerk/ocr_utils.py` for:
- `JobState` - Progress tracking dataclass
- `FailureManifest` - JSONL failure recorder
- `retry_on_transient` - Retry decorator
- Error classification constants
- `print_progress` - Progress output function
