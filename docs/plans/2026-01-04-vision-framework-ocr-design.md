# Vision Framework OCR Backend Design

**Date:** 2026-01-04
**Status:** Approved
**Implementation Approach:** Minimal Abstraction (Approach A)

## Overview

Add Apple Vision Framework as an optional OCR backend alongside Tesseract, selectable via CLI flag. Vision Framework leverages M2 Mac's Neural Engine for 3-5x faster OCR with comparable or better accuracy, while maintaining Tesseract as the default for backward compatibility and cross-platform support.

## Goals

- Provide Vision Framework as an optional OCR backend for macOS users
- Maintain Tesseract as default backend (backward compatibility)
- Allow per-run backend selection via CLI flag
- Automatic fallback from Vision to Tesseract on errors
- Zero breaking changes to existing deployments

## Non-Goals

- Replacing Tesseract entirely
- Auto-detection of best backend
- Backend-specific performance tuning (NUM_WORKERS)
- Additional cloud-based OCR backends (Azure, Google, etc.)
- Per-document backend switching

## Design

### 1. CLI Interface & Configuration

**CLI Flag Addition:**

Add `--ocr-backend` option to the `update` command in `cli.py`:

```python
@click.option(
    '--ocr-backend',
    type=click.Choice(['tesseract', 'vision'], case_sensitive=False),
    default='tesseract',
    help='OCR backend to use (tesseract or vision). Defaults to tesseract.'
)
```

**Parameter Flow:**

```
CLI (update command)
  └─> Fetcher.ocr(backend="vision")
      └─> Fetcher.do_ocr(prefix="", backend="vision")
          └─> Fetcher.do_ocr_job(..., backend="vision")
```

Update method signatures:
```python
def ocr(self, backend: str = "tesseract") -> None: ...
def do_ocr(self, prefix: str = "", backend: str = "tesseract") -> None: ...
def do_ocr_job(self, args: tuple, backend: str = "tesseract") -> None: ...
```

**Backward Compatibility:**
- Default `backend="tesseract"` means no changes required for existing code
- Existing scripts/deployments continue working unchanged

### 2. Vision Framework Integration

**Python API:**

Use `pyobjc` framework to access Apple Vision APIs:
- `Vision.VNRecognizeTextRequest` - OCR request object
- `Vision.VNImageRequestHandler` - Image processor
- `Quartz.CoreGraphics` - Image loading

**Implementation:**

Add new method to `Fetcher` class in `fetcher.py`:

```python
def _ocr_with_vision(self, image_path: Path) -> str:
    """Extract text from image using Apple Vision Framework.

    Args:
        image_path: Path to PNG image file

    Returns:
        Extracted text as string

    Raises:
        RuntimeError: If Vision Framework unavailable or processing fails
    """
    try:
        import Vision
        import Quartz
    except ImportError as e:
        raise RuntimeError(
            "Vision Framework requires pyobjc-framework-Vision. "
            "Install with: pip install pyobjc-framework-Vision pyobjc-framework-Quartz"
        ) from e

    try:
        # Load image
        image_url = Quartz.NSURL.fileURLWithPath_(str(image_path))

        # Create request with automatic language detection
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setUsesLanguageCorrection_(True)

        # Process image
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(
            image_url, None
        )
        success, error = handler.performRequests_error_([request], None)

        if not success:
            raise RuntimeError(f"Vision request failed: {error}")

        # Extract text from results
        observations = request.results()
        if not observations:
            return ""

        text = "\n".join([obs.text() for obs in observations])
        return text

    except Exception as e:
        raise RuntimeError(f"Vision OCR failed: {e}") from e
```

**Key Features:**
- Automatic language detection (no language codes needed)
- `VNRequestTextRecognitionLevelAccurate` for best quality using Neural Engine
- Language correction enabled for improved real-world accuracy
- Returns plain text string compatible with Tesseract output

### 3. Main Processing Flow

**Modification to `do_ocr_job()` method:**

Current OCR processing (lines 591-640 in `fetcher.py`) modified to:

```python
# Inside page processing loop
for i, page in enumerate(pages):
    page_num = chunk_start + i
    page_image_path = path / f"page-{page_num}.png"
    page.save(page_image_path, "PNG")

    # Backend selection with automatic fallback
    if backend == "vision":
        try:
            text = self._ocr_with_vision(page_image_path)
        except Exception as e:
            # Fall back to Tesseract on any Vision error
            output.log(
                f"Vision OCR failed for {doc_path} page {page_num}, "
                f"falling back to Tesseract: {e}",
                level="warning"
            )
            text = self._ocr_with_tesseract(page_image_path)
    else:
        # backend == "tesseract" (existing code path)
        text = self._ocr_with_tesseract(page_image_path)

    # Rest of processing unchanged (save text, upload image, etc.)
    page_txt_path = path / f"page-{page_num}.txt"
    page_txt_path.write_text(text, encoding="utf-8")

    self.pm.hook.upload_static_file(
        subdomain=self.subdomain,
        file_path=page_image_path,
        url_path=f"{prefix}/images/{meeting}/{date}/page-{page_num}.png",
    )
```

**Tesseract Extraction:**

Extract existing subprocess code into dedicated method:

```python
def _ocr_with_tesseract(self, image_path: Path) -> str:
    """Extract text from image using Tesseract.

    Args:
        image_path: Path to PNG image file

    Returns:
        Extracted text as string
    """
    text = subprocess.check_output(
        [
            "tesseract",
            "-l", self.ocr_lang,  # "eng+spa"
            "--dpi", "150",
            "--oem", "1",  # LSTM engine
            str(image_path),
            "stdout",
        ],
        stderr=subprocess.DEVNULL
    )
    return text.decode("utf-8")
```

**Language Configuration:**
- **Tesseract**: Uses existing `self.ocr_lang = "eng+spa"` (hardcoded)
- **Vision**: Automatic language detection (no configuration needed)

**Image Pipeline:**
- PNG generation remains unchanged (required for display on civicband sites)
- Both backends process the same PNG files generated by `pdf2image`
- PNGs uploaded to remote storage regardless of backend

### 4. Error Handling & Logging

**Error Categories:**

1. **Import Errors** - `pyobjc` not installed or incompatible version
   - Raised as `RuntimeError` with installation instructions
   - Triggers fallback to Tesseract

2. **Platform Errors** - Not macOS or unsupported macOS version
   - Caught by import failure or Vision API errors
   - Triggers fallback to Tesseract

3. **Runtime Errors** - Image processing failures, Vision API errors
   - Logged and triggers fallback to Tesseract
   - Document processing continues

**Fallback Behavior:**

```python
if backend == "vision":
    try:
        text = self._ocr_with_vision(page_image_path)
    except Exception as e:
        output.log(
            f"Vision OCR failed for {doc_path} page {page_num}, "
            f"falling back to Tesseract: {e}",
            level="warning"
        )
        text = self._ocr_with_tesseract(page_image_path)
```

- Any Vision error triggers automatic Tesseract fallback
- Fallback logged as warning with error details
- Processing continues without interruption
- User notified which backend actually processed each document

**Logging Enhancements:**

Add backend tracking throughout processing:

```python
# At start of do_ocr_job()
output.log(f"Processing {doc_path} with {backend} backend")

# During fallback
output.log(
    f"Vision OCR failed for {doc_path} page {page_num}, "
    f"falling back to Tesseract: {e}",
    level="warning"
)

# At completion
output.log(
    f"Completed {doc_path} using {actual_backend} backend "
    f"({pages_processed} pages in {duration:.2f}s)"
)
```

**Failure Manifest:**

Existing `FailureManifest` JSONL logging unchanged:
- Permanent failures recorded regardless of backend
- Transient errors still retried per existing logic
- Critical errors still halt processing

### 5. Dependencies & Testing

**New Dependencies:**

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
pdf = [
    "weasyprint>=60.0",
    "pdfkit>=1.0.0",
    "pdf2image>=1.16.0",
    "pypdf>=4.0.0",
]
vision = [
    "pyobjc-framework-Vision>=10.0",
    "pyobjc-framework-Quartz>=10.0",
]
```

**Installation Commands:**
- Vision users: `pip install -e ".[pdf,vision]"`
- Tesseract-only: `pip install -e ".[pdf]"` (unchanged)
- Full install: `pip install -e ".[pdf,vision]"`

**Dependency Check:**

Runtime validation when Vision selected:

```python
def _ocr_with_vision(self, image_path: Path) -> str:
    try:
        import Vision
        import Quartz
    except ImportError as e:
        raise RuntimeError(
            "Vision Framework requires pyobjc-framework-Vision. "
            "Install with: pip install pyobjc-framework-Vision pyobjc-framework-Quartz"
        ) from e
    # ... rest of implementation
```

**Testing Strategy:**

1. **Unit Tests** (`tests/test_ocr_backends.py`):
   ```python
   def test_ocr_with_tesseract():
       # Mock subprocess.check_output
       # Verify correct args passed
       # Test error handling

   @pytest.mark.skipif(not sys.platform == "darwin", reason="macOS only")
   def test_ocr_with_vision():
       # Mock Vision API
       # Verify correct configuration
       # Test error handling
   ```

2. **Integration Tests** (`tests/test_fetcher.py`):
   ```python
   def test_do_ocr_job_with_tesseract():
       # Use sample PDF fixture
       # Verify text extraction
       # Verify PNG generation/upload

   @pytest.mark.skipif(not sys.platform == "darwin", reason="macOS only")
   def test_do_ocr_job_with_vision():
       # Use same PDF fixture
       # Verify text extraction matches Tesseract structure
       # Verify fallback behavior
   ```

3. **Platform Tests** - CI/CD:
   - Tesseract tests run on Linux/macOS/Windows
   - Vision tests only run on macOS runners
   - Vision tests skipped gracefully on other platforms

**Manual Testing Checklist:**
- [ ] Run `clerk update --ocr-backend=vision` on M2 Mac
- [ ] Compare output quality vs Tesseract
- [ ] Verify PNGs uploaded correctly
- [ ] Test fallback by triggering Vision error
- [ ] Measure performance improvement
- [ ] Test with multilingual documents

### 6. Performance & Migration

**Performance Expectations:**

| Backend | Engine | Expected Speed | Hardware |
|---------|--------|----------------|----------|
| Tesseract | CPU | ~2-3s per page | All platforms |
| Vision | Neural Engine + GPU | ~0.5-1s per page | M2+ Macs |
| **Speedup** | - | **3-5x faster** | M2 Mac Mini |

**Concurrency:**
- Current `NUM_WORKERS=10` remains default for both backends
- Vision can likely handle higher concurrency (Neural Engine parallelism)
- Users can tune via `NUM_WORKERS` env var if needed
- No automatic tuning per backend (future enhancement)

**Migration Path:**

For existing clerk deployments:

1. **Phase 0 - No Changes**
   - Default backend remains Tesseract
   - Existing scripts continue working unchanged

2. **Phase 1 - Testing**
   - Install Vision dependencies: `pip install pyobjc-framework-Vision pyobjc-framework-Quartz`
   - Test on specific sites: `clerk update example.com --ocr-backend=vision`
   - Compare quality and performance

3. **Phase 2 - Gradual Rollout**
   - Update production scripts to use `--ocr-backend=vision`
   - Monitor for fallback warnings in logs
   - Rollback by removing flag if issues occur

4. **Phase 3 - Full Adoption**
   - Make Vision default on macOS (future enhancement)
   - Keep Tesseract for non-macOS deployments

**Rollback:**
- Remove `--ocr-backend=vision` from scripts
- System reverts to Tesseract (default)
- No data migration needed (text output identical)

**Future Enhancements:**

Explicitly NOT implementing now, but could add later:

- Platform-aware auto-detection (Vision on macOS, Tesseract elsewhere)
- Backend-specific `NUM_WORKERS` tuning
- Additional backends (Azure OCR, Google Cloud Vision, AWS Textract)
- Per-document backend selection based on language/quality
- Confidence scores from Vision API for quality monitoring
- Benchmark mode to compare backends on same documents

**Documentation Updates:**

Add to README or docs:

```markdown
## OCR Backends

Clerk supports two OCR backends:

### Tesseract (Default)
- Cross-platform (Linux, macOS, Windows)
- Supports 100+ languages
- Requires tesseract binary installed
- Usage: `clerk update` (default) or `clerk update --ocr-backend=tesseract`

### Vision Framework (macOS only)
- Requires M1+ Mac (Neural Engine)
- 3-5x faster than Tesseract on Apple Silicon
- Automatic language detection
- Requires: `pip install pyobjc-framework-Vision pyobjc-framework-Quartz`
- Usage: `clerk update --ocr-backend=vision`

### Fallback Behavior
If Vision is selected but fails (missing dependencies, errors), clerk automatically falls back to Tesseract and logs a warning.
```

## Implementation Checklist

- [ ] Add `--ocr-backend` CLI flag to `update` command
- [ ] Update `Fetcher.ocr()`, `do_ocr()`, `do_ocr_job()` signatures
- [ ] Implement `_ocr_with_vision()` method
- [ ] Extract `_ocr_with_tesseract()` method from existing code
- [ ] Add backend selection logic in `do_ocr_job()`
- [ ] Add fallback error handling
- [ ] Update logging statements with backend tracking
- [ ] Add `vision` optional dependencies to `pyproject.toml`
- [ ] Write unit tests for both backends
- [ ] Write integration tests for `do_ocr_job()`
- [ ] Update documentation (README, CLI help text)
- [ ] Manual testing on M2 Mac
- [ ] Performance benchmarking

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Vision Framework unavailable on older macOS | Users can't use Vision backend | Automatic fallback to Tesseract |
| Vision accuracy worse than Tesseract | Poor OCR quality | Easy rollback via CLI flag |
| Vision API changes in future macOS versions | Code breaks on OS upgrade | Pin pyobjc version, test on new OS releases |
| Code duplication between backends | Maintenance burden | Accept for now, refactor if adding 3+ backends |
| Performance regression for Tesseract path | Slower processing | Tesseract code path unchanged (no regression) |

## Success Criteria

- [ ] `clerk update --ocr-backend=vision` works on M2 Mac
- [ ] Text output quality comparable to Tesseract
- [ ] 3-5x performance improvement measured
- [ ] Automatic fallback works when Vision fails
- [ ] Zero breaking changes to existing deployments
- [ ] Tests pass on both macOS and Linux CI runners
- [ ] Documentation clearly explains both backends
