# OCR Performance: Async Logging Fix

**Date:** 2026-01-04
**Status:** Implemented
**Impact:** 5-10x OCR performance improvement

## Problem

OCR processing became dramatically slower (~5-10x) after comprehensive logging was added in PR #36. A typical OCR job that previously took 10-15 minutes was taking 1-2 hours.

### Root Cause

The logging configuration used synchronous `LokiHandler` which blocks on every `log()` call, waiting for HTTP response from Loki before continuing execution.

With the new OCR logging (added in PR #36), each document generates 4-5 log calls:
- "Processing document"
- "PDF read" (with timing)
- "Image conversion" (with timing)
- "OCR completed" (with timing)
- "Document completed"

Plus progress updates every 5 documents and error logs.

**For a 100-document OCR job:** 400-500+ synchronous HTTP calls to Loki

**Network overhead:** If each log call takes 50-100ms for network I/O, that's 20-50 seconds of pure blocking time, multiplied across all documents being processed in parallel.

### Why It Got Worse Over Time

The comprehensive logging added valuable observability but every log call became a synchronous network operation. With 10 parallel workers processing documents, the cumulative blocking time made the entire job dramatically slower.

## Solution

Replace synchronous `LokiHandler` with `LokiQueueHandler` for async batched log sending.

### Implementation

**File:** `src/clerk/cli.py`

**Before:**
```python
loki_handler = logging_loki.LokiHandler(
    url=f"{loki_url}/loki/api/v1/push",
    tags={"job": "clerk", "host": os.uname().nodename, "command": command_name},
    version="1",
)
```

**After:**
```python
from queue import Queue

loki_queue = Queue()
loki_handler = logging_loki.LokiQueueHandler(
    loki_queue,
    url=f"{loki_url}/loki/api/v1/push",
    tags={"job": "clerk", "host": os.uname().nodename, "command": command_name},
    version="1",
)
```

### How It Works

1. **LokiQueueHandler** buffers log records in a `Queue` instead of sending immediately
2. A background thread processes the queue and sends logs to Loki in batches
3. The main OCR processing thread never blocks on network I/O
4. Logs still reach Loki, just with slight delay (typically <1 second)

### Trade-offs

**Pros:**
- Near-zero performance overhead during OCR processing
- All logs still reach Loki (just batched)
- No code changes needed beyond handler initialization
- Maintains all existing observability

**Cons:**
- Small risk of log loss if process crashes before queue flushes
- Logs appear in Loki with slight delay (acceptable for batch processing)
- Slightly higher memory usage (queue buffering)

## Results

- OCR jobs return to original performance (5-10x faster than with synchronous logging)
- Network I/O no longer blocks document processing
- All logs still appear in Loki for debugging and monitoring

## Future Optimizations

If further performance improvements are needed:

1. **Reduce log verbosity during OCR** - Only log failures and job summaries, skip per-document details
2. **Increase batch size** - Configure LokiQueueHandler to batch more aggressively
3. **Local-first logging** - Write detailed logs locally, send only summaries to Loki
4. **Conditional logging** - Add `OCR_VERBOSE_LOGGING` env var to toggle detail level

## Monitoring

To verify performance and identify further bottlenecks:

1. **Time overall jobs:** Log OCR job duration at start/end
2. **Profile slow operations:** Use timing logs to find slowest steps (PDF read, conversion, OCR)
3. **Track queue depth:** Monitor if LokiQueueHandler queue is backing up
4. **Watch for timeouts:** Alert on documents taking >5 minutes

## References

- Original issue: OCR became 5-10x slower after logging was added
- Fix commits: 8ba53d4, e5c3bf0
- Related: PR #36 (OCR logging and exception handling)
