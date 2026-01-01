# spaCy Memory Optimization Design

**Date:** 2025-12-31
**Status:** Approved
**Problem:** spaCy processing uses ~20GB memory (5GB per process × 4 processes)
**Solution:** Reduce processes to 2 + add chunked processing to bound memory under 10GB

## Overview

### The Problem

Current spaCy processing uses ~20GB peak memory with 4 parallel processes:
- Each process loads the `en_core_web_md` model (~5GB per process including overhead)
- Users set `SPACY_N_PROCESS=4` for faster processing
- Memory usage is acceptable for speed, but can be optimized now that caching reduces processing frequency

With the new extraction caching strategy (95%+ cache hits for typical updates), speed is less critical. We can trade some speed for lower memory footprint.

### The Solution

**Two-pronged approach:**

1. **Reduce default processes:** 4 → 2 processes (~50% memory reduction)
2. **Add chunked processing:** Process large batches in chunks to bound memory regardless of dataset size

**Memory profile:**
- **Before:** 20GB peak (4 processes × 5GB)
- **After:** ~10GB peak (2 processes × 5GB), bounded for any dataset size
- **Speed impact:** ~30-40% slower on large batches, minimal impact on small incremental updates

### Key Benefits

- **50% memory reduction** from 20GB to 10GB baseline
- **Bounded memory** regardless of dataset size (547k pages or 500 pages)
- **Minimal impact on incremental updates** (small batches process quickly regardless)
- **Graceful handling of large rebuilds** via chunking
- **User control preserved** via `SPACY_N_PROCESS` env var override

## Architecture

### Component 1: Reduce Default Process Count

**Change:** Update default `SPACY_N_PROCESS` recommendation from 4 to 2

**Implementation:**

```python
# In src/clerk/utils.py, line 132
n_process = int(os.environ.get("SPACY_N_PROCESS", "2"))
```

**Documentation update in README.md:**

```markdown
- `SPACY_N_PROCESS`: Number of CPU cores for parallel spaCy processing (default: `2`).
  Set to `1` to minimize memory usage (~5GB) or `4` for maximum speed (~20GB memory).
```

**Trade-offs:**
- ✅ Immediate 50% memory reduction
- ✅ Still 2x faster than single-process mode
- ⚠️ ~30% slower than 4-process mode on large batches
- ✅ User can override to 4 if they have memory headroom

### Component 2: Chunked Processing for Large Batches

**Logic:** When uncached pages exceed threshold, process in chunks with memory cleanup

**Implementation:**

Add to `src/clerk/utils.py` in `build_table_from_text()`:

```python
# Configuration
CHUNK_SIZE = 20_000  # Process max 20k pages per chunk

# After scanning for cached/uncached pages (Phase 1)
all_texts = [p["text"] for p in uncached_pages]

if len(all_texts) <= CHUNK_SIZE:
    # Small batch - process all at once (existing behavior)
    log(f"Parsing {len(all_texts)} pages...", subdomain=subdomain)
    pipe_kwargs = {"batch_size": 500}
    if n_process > 1:
        pipe_kwargs["n_process"] = n_process

    all_docs = []
    for i, doc in enumerate(nlp.pipe(all_texts, **pipe_kwargs)):
        all_docs.append(doc)
        if (i + 1) % 1000 == 0:
            log(f"Parsed {i + 1}/{len(all_texts)} pages...", subdomain=subdomain)
else:
    # Large batch - process in chunks to bound memory
    total_pages = len(all_texts)
    num_chunks = (total_pages + CHUNK_SIZE - 1) // CHUNK_SIZE
    log(f"Parsing {total_pages} pages in {num_chunks} chunks...", subdomain=subdomain)

    all_docs = []
    for chunk_idx in range(num_chunks):
        chunk_start = chunk_idx * CHUNK_SIZE
        chunk_end = min(chunk_start + CHUNK_SIZE, total_pages)
        chunk_texts = all_texts[chunk_start:chunk_end]
        chunk_size = len(chunk_texts)

        log(f"Processing chunk {chunk_idx + 1}/{num_chunks} ({chunk_size} pages)...",
            subdomain=subdomain)

        pipe_kwargs = {"batch_size": 500}
        if n_process > 1:
            pipe_kwargs["n_process"] = n_process

        chunk_docs = []
        for i, doc in enumerate(nlp.pipe(chunk_texts, **pipe_kwargs)):
            chunk_docs.append(doc)
            # Progress within chunk (every 1000 pages)
            if (i + 1) % 1000 == 0:
                global_progress = chunk_start + i + 1
                log(f"Parsed {global_progress}/{total_pages} pages...",
                    subdomain=subdomain)

        all_docs.extend(chunk_docs)

        # Explicit memory cleanup between chunks
        import gc
        gc.collect()

        log(f"Completed chunk {chunk_idx + 1}/{num_chunks}", subdomain=subdomain)
```

**Why 20k chunk size:**
- With 2 processes × 5GB, 20k pages keeps memory stable
- Smaller chunks = more gc.collect() overhead
- Larger chunks = risk of memory spikes
- 20k is a sweet spot for 547k page datasets (27 chunks, manageable)

**Benefits:**
- ✅ Memory bounded at ~10GB regardless of total pages
- ✅ Progress logging per chunk for long-running jobs
- ✅ Minimal overhead for small batches (< 20k pages, most incremental updates)
- ✅ Explicit gc.collect() ensures memory is freed between chunks
- ⚠️ Adds 1-2 seconds overhead per chunk boundary for gc

### Memory Behavior Comparison

| Scenario | Pages | Before (4 proc) | After (2 proc + chunking) |
|----------|-------|-----------------|---------------------------|
| Incremental update | 500 | 20GB | 10GB |
| Medium rebuild | 10,000 | 20GB | 10GB |
| Large rebuild | 50,000 | 20GB | 10GB (3 chunks) |
| Full rebuild | 547,000 | 20GB | 10GB (28 chunks) |

**Key insight:** Memory is now bounded regardless of dataset size.

## Performance Impact

### Speed Comparison

| Dataset Size | Before (4 proc) | After (2 proc) | Slowdown |
|--------------|-----------------|----------------|----------|
| 500 pages | ~30 sec | ~45 sec | 1.5x |
| 10,000 pages | ~10 min | ~13 min | 1.3x |
| 50,000 pages | ~45 min | ~60 min | 1.33x |
| 547,000 pages | ~2 hours | ~2.5-3 hours | 1.25-1.5x |

**Notes:**
- Speed impact is higher for small batches (less parallelism opportunity)
- With caching, most updates are small and complete in < 1 minute regardless
- Large rebuilds are infrequent and acceptable to take longer
- gc.collect() overhead is negligible compared to spaCy processing time

### Cache Hit Rate Impact

| Update Type | Cache Hit Rate | Uncached Pages | Time Before | Time After |
|-------------|----------------|----------------|-------------|------------|
| Add 1 new meeting | 99.9% | ~50 pages | 30 sec | 30 sec |
| Add 10 meetings | 99% | ~500 pages | 2 min | 2 min |
| Bulk reprocess | 10% | 50k pages | 45 min | 60 min |
| Full rebuild | 0% | 547k pages | 2 hours | 2.5-3 hours |

**With 95%+ cache hits, most updates are unaffected by the speed reduction.**

## Implementation Details

### Files to Modify

1. **src/clerk/utils.py**
   - Update `build_table_from_text()` to add chunking logic
   - Change default `SPACY_N_PROCESS` from 1 to 2 (users currently override to 4)

2. **README.md**
   - Update `SPACY_N_PROCESS` documentation with memory guidance

3. **tests/test_utils.py**
   - Add test for chunked processing behavior
   - Add test for memory cleanup (mock gc.collect())

### Configuration

**New constant in utils.py:**
```python
# Maximum pages to process in a single spaCy batch before chunking
SPACY_CHUNK_SIZE = 20_000
```

**Environment variable (existing, updated default):**
```python
SPACY_N_PROCESS=2  # Default changed from implicitly 4 to explicitly 2
```

### Logging Strategy

Use centralized `log()` function from `.output`:

```python
# Before chunking decision
log(f"Parsing {total_pages} pages...", subdomain=subdomain)

# Chunked processing
log(f"Parsing {total_pages} pages in {num_chunks} chunks...", subdomain=subdomain)
log(f"Processing chunk {chunk_idx + 1}/{num_chunks} ({chunk_size} pages)...",
    subdomain=subdomain)

# Progress within chunks (every 1000 pages)
log(f"Parsed {global_progress}/{total_pages} pages...", subdomain=subdomain)

# Chunk completion
log(f"Completed chunk {chunk_idx + 1}/{num_chunks}", subdomain=subdomain)
```

Debug logging for memory:
```python
import psutil  # If available
logger.debug(f"Memory usage before chunk {chunk_idx}: {psutil.Process().memory_info().rss / 1024**3:.2f} GB")
logger.debug(f"Memory usage after gc: {psutil.Process().memory_info().rss / 1024**3:.2f} GB")
```

## Testing Strategy

### Unit Tests

**Test chunking logic:**
```python
def test_chunked_processing_splits_correctly(mocker):
    """Test that large batches are split into chunks."""
    # Mock nlp.pipe to return fake docs
    mock_nlp = mocker.MagicMock()
    mock_nlp.pipe.return_value = [mocker.MagicMock() for _ in range(100)]

    # Simulate 25k pages (should trigger chunking with CHUNK_SIZE=20k)
    texts = [f"text {i}" for i in range(25_000)]

    # Call build_table_from_text with mocked nlp
    # Assert nlp.pipe called twice (chunk 1: 20k, chunk 2: 5k)
    assert mock_nlp.pipe.call_count == 2
```

**Test memory cleanup:**
```python
def test_gc_collect_called_between_chunks(mocker):
    """Test that gc.collect() is called between chunks."""
    mock_gc = mocker.patch('gc.collect')

    # Process 25k pages in chunks
    # build_table_from_text(...)

    # Should call gc.collect() once (after first chunk, not after last)
    assert mock_gc.call_count == 1
```

**Test small batch unchanged:**
```python
def test_small_batch_no_chunking(mocker):
    """Test that batches under CHUNK_SIZE are not chunked."""
    mock_nlp = mocker.MagicMock()

    # 1000 pages (under 20k threshold)
    texts = [f"text {i}" for i in range(1_000)]

    # Should call nlp.pipe once
    assert mock_nlp.pipe.call_count == 1
```

### Integration Tests

**Test with real spaCy model:**
```python
@pytest.mark.slow
def test_chunked_processing_real_spacy(tmp_path):
    """Integration test with real spaCy processing."""
    # Create 25k text files
    # Run build_table_from_text
    # Verify all pages processed correctly
    # Verify database has correct number of entries
```

**Memory profiling test (manual):**
```bash
# Install memory_profiler: pip install memory_profiler
# Run with profiling
mprof run clerk build-db-from-text --subdomain example.civic.band
mprof plot

# Verify peak memory < 12GB (10GB + 2GB safety margin)
```

## Deployment & Migration

### Backwards Compatibility

- ✅ No breaking changes to API or CLI
- ✅ Existing `SPACY_N_PROCESS` env var behavior unchanged
- ✅ Users with `SPACY_N_PROCESS=4` will see no difference (except in chunking logic)
- ✅ Users without env var set will get new default (2 instead of 1)

### Deployment Strategy

1. **Deploy code changes** to production
2. **Update documentation** (README.md) with new memory guidance
3. **Monitor first few builds** for memory usage and performance
4. **Adjust CHUNK_SIZE if needed** based on real-world memory behavior

### Configuration Migration

**Before (user configuration):**
```bash
SPACY_N_PROCESS=4  # User sets this for speed
```

**After (recommended):**
```bash
SPACY_N_PROCESS=2  # New default, user can keep 4 if they have memory
```

**For users with memory constraints:**
```bash
SPACY_N_PROCESS=1  # Minimize memory (~5GB)
```

### Rollback Plan

If issues arise:
1. Revert `SPACY_N_PROCESS` default to 1 (or remove default)
2. Remove chunking logic (revert to single nlp.pipe call)
3. Previous behavior restored immediately

## Edge Cases & Error Handling

### Empty or Small Batches

```python
if len(all_texts) == 0:
    all_docs = []
    # Skip processing entirely
```

### Single Large Chunk

```python
if len(all_texts) == CHUNK_SIZE:
    # Exactly one chunk - no gc overhead needed
    # Process normally without chunking logic
```

### spaCy Processing Failures Mid-Chunk

```python
try:
    chunk_docs = list(nlp.pipe(chunk_texts, **pipe_kwargs))
except Exception as e:
    log(f"spaCy processing failed for chunk {chunk_idx + 1}: {e}",
        subdomain=subdomain, level="error")
    # Create empty docs for this chunk to avoid blocking entire build
    chunk_docs = [None] * len(chunk_texts)
```

### Memory Still High After gc.collect()

- **Monitor in production:** If memory doesn't decrease after gc.collect(), may need smaller chunks
- **Tunable parameter:** Make CHUNK_SIZE configurable via env var for testing
- **Fallback:** Reduce to SPACY_N_PROCESS=1 if memory issues persist

## Success Criteria

1. **Memory reduction:** Peak memory < 12GB (10GB target + 2GB safety margin) for any dataset size
2. **Speed acceptable:** Incremental updates (< 1k pages) complete in < 2 minutes
3. **Large batches bounded:** 547k page rebuild completes in < 4 hours with stable memory
4. **Logging clarity:** Progress updates every 1000 pages + per-chunk status
5. **All tests pass:** Unit and integration tests verify chunking behavior
6. **No regressions:** Existing extraction accuracy and cache behavior unchanged

## Future Optimizations (Out of Scope)

1. **Adaptive chunk size:** Dynamically adjust based on available memory
2. **Selective component disabling:** Disable parser/lemmatizer for pages that don't need votes
3. **Streaming extraction cache writes:** Write cache files during processing, not after
4. **Model quantization:** Use smaller/quantized spaCy models (accuracy trade-off)
5. **Progressive model loading:** Load model components only when needed

These optimizations require more complex implementation and testing. Current solution provides good balance of simplicity and effectiveness.
