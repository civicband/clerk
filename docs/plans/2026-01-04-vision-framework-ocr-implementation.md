# Vision Framework OCR Backend Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Apple Vision Framework as an optional OCR backend alongside Tesseract, selectable via `--ocr-backend` CLI flag.

**Architecture:** Minimal abstraction approach - add Vision as parallel code path with automatic fallback to Tesseract on errors. Backend selection via CLI flag, defaults to Tesseract for backward compatibility.

**Tech Stack:** Python 3.12, pyobjc-framework-Vision, Apple Vision Framework, Click (CLI)

---

## Task 1: Add pyobjc Dependencies to pyproject.toml

**Files:**
- Modify: `pyproject.toml:21-27`

**Step 1: Add vision optional dependencies**

Update the `[project.optional-dependencies]` section:

```toml
[project.optional-dependencies]
pdf = [
    "weasyprint>=60.0",
    "pdfkit>=1.0.0",
    "pdf2image>=1.16.0",
    "pypdf>=4.0.0",
]
extraction = [
    "spacy>=3.5.0",
    "numpy<2",  # spaCy/torch not yet compatible with NumPy 2.x
]
vision = [
    "pyobjc-framework-Vision>=10.0",
    "pyobjc-framework-Quartz>=10.0",
]
dev = [
    "pytest>=7.4.0",
    "pytest-cov>=4.1.0",
    "pytest-mock>=3.12.0",
    "pytest-click>=1.1.0",
    "ruff>=0.1.0",
    "mypy>=1.7.0",
    "pre-commit>=3.5.0",
    "faker>=20.0.0",
]
```

**Step 2: Install vision dependencies**

Run: `uv sync --extra vision`

Expected: Packages installed successfully

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "Add pyobjc dependencies for Vision Framework OCR backend"
```

---

## Task 2: Add --ocr-backend CLI Flag

**Files:**
- Modify: `src/clerk/cli.py:269-300` (update command)
- Test: `tests/test_cli.py`

**Step 1: Write failing test for CLI flag**

Add to `tests/test_cli.py`:

```python
def test_update_command_accepts_ocr_backend_flag(cli_runner, tmp_path):
    """Test that update command accepts --ocr-backend flag."""
    result = cli_runner.invoke(
        cli,
        ["--storage-dir", str(tmp_path), "update", "test.example.com", "--ocr-backend", "vision"],
        catch_exceptions=False,
    )
    # Should not fail due to unknown option
    assert "--ocr-backend" not in result.output or result.exit_code != 2


def test_ocr_backend_defaults_to_tesseract(cli_runner, tmp_path, mocker):
    """Test that OCR backend defaults to tesseract."""
    mock_fetcher = mocker.patch("clerk.cli.Fetcher")

    cli_runner.invoke(
        cli,
        ["--storage-dir", str(tmp_path), "update", "test.example.com"],
        catch_exceptions=False,
    )

    # Verify ocr() was called with default backend
    mock_fetcher.return_value.ocr.assert_called_once()


def test_ocr_backend_vision_passed_to_fetcher(cli_runner, tmp_path, mocker):
    """Test that --ocr-backend=vision is passed to Fetcher.ocr()."""
    mock_fetcher = mocker.patch("clerk.cli.Fetcher")

    cli_runner.invoke(
        cli,
        ["--storage-dir", str(tmp_path), "update", "test.example.com", "--ocr-backend", "vision"],
        catch_exceptions=False,
    )

    # Verify ocr() was called with vision backend
    mock_fetcher.return_value.ocr.assert_called_once_with(backend="vision")
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src uv run python -m pytest tests/test_cli.py::test_update_command_accepts_ocr_backend_flag -v`

Expected: FAIL (option doesn't exist yet)

**Step 3: Add --ocr-backend flag to update command**

In `src/clerk/cli.py`, find the `update` command and add the option:

```python
@cli.command()
@click.argument("subdomain")
@click.option(
    "--ocr-backend",
    type=click.Choice(["tesseract", "vision"], case_sensitive=False),
    default="tesseract",
    help="OCR backend to use (tesseract or vision). Defaults to tesseract.",
)
@click.pass_context
def update(ctx, subdomain, ocr_backend):
    """Fetch, OCR, transform, and deploy a site."""
    # ... existing code ...

    # Find where fetcher.ocr() is called and update it
    fetcher.ocr(backend=ocr_backend)

    # ... rest of existing code ...
```

**Step 4: Update Fetcher.ocr() signature**

In `src/clerk/fetcher.py`, update the `ocr()` method signature:

```python
def ocr(self, backend: str = "tesseract") -> None:
    """Run OCR on all PDFs for this subdomain.

    Args:
        backend: OCR backend to use ('tesseract' or 'vision')
    """
    start_time = time.time()

    # Process minutes
    self.do_ocr(prefix="", backend=backend)

    # Process agendas
    self.do_ocr(prefix="/_agendas", backend=backend)

    duration = time.time() - start_time
    output.log(f"OCR completed in {duration:.2f}s")
```

**Step 5: Update do_ocr() signature**

In `src/clerk/fetcher.py`, update the `do_ocr()` method signature:

```python
def do_ocr(self, prefix: str = "", backend: str = "tesseract") -> None:
    """Process OCR for a specific prefix.

    Args:
        prefix: URL prefix (empty for minutes, "/_agendas" for agendas)
        backend: OCR backend to use ('tesseract' or 'vision')
    """
    # ... existing code ...

    # When calling do_ocr_job, pass backend
    future_to_doc = {
        executor.submit(self.do_ocr_job, doc, backend=backend): doc
        for doc in job_queue
    }
```

**Step 6: Update do_ocr_job() signature**

In `src/clerk/fetcher.py`, update the `do_ocr_job()` method signature:

```python
def do_ocr_job(self, args: tuple, backend: str = "tesseract") -> None:
    """Process OCR for a single document.

    Args:
        args: Tuple of (prefix, meeting, date)
        backend: OCR backend to use ('tesseract' or 'vision')
    """
    prefix, meeting, date = args
    # ... rest of existing code ...
```

**Step 7: Run tests to verify they pass**

Run: `PYTHONPATH=src uv run python -m pytest tests/test_cli.py::test_update_command_accepts_ocr_backend_flag tests/test_cli.py::test_ocr_backend_defaults_to_tesseract tests/test_cli.py::test_ocr_backend_vision_passed_to_fetcher -v`

Expected: PASS

**Step 8: Commit**

```bash
git add src/clerk/cli.py src/clerk/fetcher.py tests/test_cli.py
git commit -m "Add --ocr-backend CLI flag and pass through to Fetcher"
```

---

## Task 3: Extract _ocr_with_tesseract() Method

**Files:**
- Modify: `src/clerk/fetcher.py:507-693`
- Test: `tests/test_fetcher.py`

**Step 1: Write test for _ocr_with_tesseract()**

Add to `tests/test_fetcher.py`:

```python
def test_ocr_with_tesseract_extracts_text(tmp_path, mocker):
    """Test that _ocr_with_tesseract extracts text from an image."""
    from clerk.fetcher import Fetcher

    # Create a mock image
    image_path = tmp_path / "test.png"
    image_path.write_bytes(b"fake png data")

    # Mock subprocess to return test text
    mock_check_output = mocker.patch("subprocess.check_output")
    mock_check_output.return_value = b"Test OCR text\nLine 2"

    fetcher = Fetcher("test.example.com", storage_dir=str(tmp_path))
    result = fetcher._ocr_with_tesseract(image_path)

    assert result == "Test OCR text\nLine 2"

    # Verify tesseract was called with correct args
    mock_check_output.assert_called_once()
    args = mock_check_output.call_args[0][0]
    assert args[0] == "tesseract"
    assert "-l" in args
    assert "eng+spa" in args
    assert "--dpi" in args
    assert "150" in args
    assert "--oem" in args
    assert "1" in args
    assert str(image_path) in args
    assert "stdout" in args


def test_ocr_with_tesseract_handles_subprocess_error(tmp_path, mocker):
    """Test that _ocr_with_tesseract handles subprocess errors."""
    from clerk.fetcher import Fetcher
    import subprocess

    image_path = tmp_path / "test.png"
    image_path.write_bytes(b"fake png data")

    # Mock subprocess to raise error
    mock_check_output = mocker.patch("subprocess.check_output")
    mock_check_output.side_effect = subprocess.CalledProcessError(1, "tesseract")

    fetcher = Fetcher("test.example.com", storage_dir=str(tmp_path))

    with pytest.raises(subprocess.CalledProcessError):
        fetcher._ocr_with_tesseract(image_path)
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src uv run python -m pytest tests/test_fetcher.py::test_ocr_with_tesseract_extracts_text -v`

Expected: FAIL (method doesn't exist yet)

**Step 3: Extract Tesseract code into _ocr_with_tesseract() method**

In `src/clerk/fetcher.py`, add the new method before `do_ocr_job()`:

```python
def _ocr_with_tesseract(self, image_path: Path) -> str:
    """Extract text from image using Tesseract OCR.

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

**Step 4: Update do_ocr_job() to use _ocr_with_tesseract()**

In `src/clerk/fetcher.py`, find the Tesseract subprocess call in `do_ocr_job()` (around line 601-614) and replace it:

```python
# OLD CODE (remove):
# text = subprocess.check_output(
#     ["tesseract", "-l", self.ocr_lang, "--dpi", "150", "--oem", "1",
#      page_image_path, "stdout"],
#     stderr=subprocess.DEVNULL
# ).decode("utf-8")

# NEW CODE:
text = self._ocr_with_tesseract(page_image_path)
```

**Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src uv run python -m pytest tests/test_fetcher.py::test_ocr_with_tesseract_extracts_text tests/test_fetcher.py::test_ocr_with_tesseract_handles_subprocess_error -v`

Expected: PASS

**Step 6: Commit**

```bash
git add src/clerk/fetcher.py tests/test_fetcher.py
git commit -m "Extract Tesseract OCR logic into _ocr_with_tesseract method"
```

---

## Task 4: Implement _ocr_with_vision() Method

**Files:**
- Modify: `src/clerk/fetcher.py`
- Test: `tests/test_fetcher.py`

**Step 1: Write test for _ocr_with_vision()**

Add to `tests/test_fetcher.py`:

```python
import sys
import pytest


@pytest.mark.skipif(sys.platform != "darwin", reason="Vision Framework only on macOS")
def test_ocr_with_vision_extracts_text(tmp_path, mocker):
    """Test that _ocr_with_vision extracts text from an image."""
    from clerk.fetcher import Fetcher

    # Create a mock image
    image_path = tmp_path / "test.png"
    image_path.write_bytes(b"fake png data")

    # Mock Vision Framework
    mock_vision = mocker.MagicMock()
    mock_quartz = mocker.MagicMock()

    # Mock the request and observations
    mock_request = mocker.MagicMock()
    mock_observation = mocker.MagicMock()
    mock_observation.text.return_value = "Vision OCR text"
    mock_request.results.return_value = [mock_observation]

    mock_vision.VNRecognizeTextRequest.alloc.return_value.init.return_value = mock_request
    mock_vision.VNRequestTextRecognitionLevelAccurate = 1

    # Mock handler
    mock_handler = mocker.MagicMock()
    mock_handler.performRequests_error_.return_value = (True, None)
    mock_vision.VNImageRequestHandler.alloc.return_value.initWithURL_options_.return_value = mock_handler

    # Mock NSURL
    mock_url = mocker.MagicMock()
    mock_quartz.NSURL.fileURLWithPath_.return_value = mock_url

    # Patch imports
    mocker.patch.dict("sys.modules", {"Vision": mock_vision, "Quartz": mock_quartz})

    fetcher = Fetcher("test.example.com", storage_dir=str(tmp_path))
    result = fetcher._ocr_with_vision(image_path)

    assert result == "Vision OCR text"


@pytest.mark.skipif(sys.platform != "darwin", reason="Vision Framework only on macOS")
def test_ocr_with_vision_handles_import_error(tmp_path):
    """Test that _ocr_with_vision raises helpful error when pyobjc not installed."""
    from clerk.fetcher import Fetcher
    import sys

    # Remove Vision from sys.modules if present
    if "Vision" in sys.modules:
        del sys.modules["Vision"]
    if "Quartz" in sys.modules:
        del sys.modules["Quartz"]

    image_path = tmp_path / "test.png"
    image_path.write_bytes(b"fake png data")

    fetcher = Fetcher("test.example.com", storage_dir=str(tmp_path))

    with pytest.raises(RuntimeError, match="Vision Framework requires pyobjc"):
        fetcher._ocr_with_vision(image_path)


@pytest.mark.skipif(sys.platform != "darwin", reason="Vision Framework only on macOS")
def test_ocr_with_vision_handles_vision_error(tmp_path, mocker):
    """Test that _ocr_with_vision handles Vision API errors."""
    from clerk.fetcher import Fetcher

    image_path = tmp_path / "test.png"
    image_path.write_bytes(b"fake png data")

    # Mock Vision Framework to raise error
    mock_vision = mocker.MagicMock()
    mock_quartz = mocker.MagicMock()

    mock_vision.VNRecognizeTextRequest.alloc.return_value.init.side_effect = Exception("Vision failed")

    mocker.patch.dict("sys.modules", {"Vision": mock_vision, "Quartz": mock_quartz})

    fetcher = Fetcher("test.example.com", storage_dir=str(tmp_path))

    with pytest.raises(RuntimeError, match="Vision OCR failed"):
        fetcher._ocr_with_vision(image_path)
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src uv run python -m pytest tests/test_fetcher.py::test_ocr_with_vision_extracts_text -v`

Expected: FAIL (method doesn't exist yet)

**Step 3: Implement _ocr_with_vision() method**

In `src/clerk/fetcher.py`, add the new method after `_ocr_with_tesseract()`:

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
        if isinstance(e, RuntimeError):
            raise
        raise RuntimeError(f"Vision OCR failed: {e}") from e
```

**Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src uv run python -m pytest tests/test_fetcher.py -k "test_ocr_with_vision" -v`

Expected: PASS (or SKIPPED on non-macOS)

**Step 5: Commit**

```bash
git add src/clerk/fetcher.py tests/test_fetcher.py
git commit -m "Implement Vision Framework OCR backend method"
```

---

## Task 5: Add Backend Selection Logic in do_ocr_job()

**Files:**
- Modify: `src/clerk/fetcher.py:507-693`
- Test: `tests/test_fetcher.py`

**Step 1: Write integration test for backend selection**

Add to `tests/test_fetcher.py`:

```python
def test_do_ocr_job_uses_tesseract_backend(tmp_path, mocker):
    """Test that do_ocr_job uses Tesseract when backend='tesseract'."""
    from clerk.fetcher import Fetcher

    # Setup
    fetcher = Fetcher("test.example.com", storage_dir=str(tmp_path))

    # Mock the OCR methods
    mock_tesseract = mocker.patch.object(fetcher, "_ocr_with_tesseract", return_value="Tesseract text")
    mock_vision = mocker.patch.object(fetcher, "_ocr_with_vision", return_value="Vision text")

    # Mock PDF processing
    mocker.patch("clerk.fetcher.PdfReader")
    mocker.patch("clerk.fetcher.convert_from_path", return_value=[mocker.MagicMock()])
    mocker.patch.object(fetcher.pm.hook, "upload_static_file")

    # Create test PDF
    pdf_dir = tmp_path / "test.example.com" / "pdfs" / "meeting"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "2024-01-01.pdf").write_bytes(b"fake pdf")

    # Run with tesseract backend
    fetcher.do_ocr_job(("", "meeting", "2024-01-01"), backend="tesseract")

    # Verify Tesseract was called, Vision was not
    assert mock_tesseract.called
    assert not mock_vision.called


@pytest.mark.skipif(sys.platform != "darwin", reason="Vision Framework only on macOS")
def test_do_ocr_job_uses_vision_backend(tmp_path, mocker):
    """Test that do_ocr_job uses Vision when backend='vision'."""
    from clerk.fetcher import Fetcher

    # Setup
    fetcher = Fetcher("test.example.com", storage_dir=str(tmp_path))

    # Mock the OCR methods
    mock_tesseract = mocker.patch.object(fetcher, "_ocr_with_tesseract", return_value="Tesseract text")
    mock_vision = mocker.patch.object(fetcher, "_ocr_with_vision", return_value="Vision text")

    # Mock PDF processing
    mocker.patch("clerk.fetcher.PdfReader")
    mocker.patch("clerk.fetcher.convert_from_path", return_value=[mocker.MagicMock()])
    mocker.patch.object(fetcher.pm.hook, "upload_static_file")

    # Create test PDF
    pdf_dir = tmp_path / "test.example.com" / "pdfs" / "meeting"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "2024-01-01.pdf").write_bytes(b"fake pdf")

    # Run with vision backend
    fetcher.do_ocr_job(("", "meeting", "2024-01-01"), backend="vision")

    # Verify Vision was called, Tesseract was not (unless fallback)
    assert mock_vision.called


def test_do_ocr_job_falls_back_to_tesseract_on_vision_error(tmp_path, mocker):
    """Test that do_ocr_job falls back to Tesseract when Vision fails."""
    from clerk.fetcher import Fetcher

    # Setup
    fetcher = Fetcher("test.example.com", storage_dir=str(tmp_path))

    # Mock Vision to fail, Tesseract to succeed
    mock_vision = mocker.patch.object(
        fetcher, "_ocr_with_vision",
        side_effect=RuntimeError("Vision failed")
    )
    mock_tesseract = mocker.patch.object(fetcher, "_ocr_with_tesseract", return_value="Tesseract text")

    # Mock output.log to verify fallback warning
    mock_log = mocker.patch("clerk.fetcher.output.log")

    # Mock PDF processing
    mocker.patch("clerk.fetcher.PdfReader")
    mocker.patch("clerk.fetcher.convert_from_path", return_value=[mocker.MagicMock()])
    mocker.patch.object(fetcher.pm.hook, "upload_static_file")

    # Create test PDF
    pdf_dir = tmp_path / "test.example.com" / "pdfs" / "meeting"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "2024-01-01.pdf").write_bytes(b"fake pdf")

    # Run with vision backend
    fetcher.do_ocr_job(("", "meeting", "2024-01-01"), backend="vision")

    # Verify both were called (Vision failed, fell back to Tesseract)
    assert mock_vision.called
    assert mock_tesseract.called

    # Verify fallback warning was logged
    log_calls = [call[0][0] for call in mock_log.call_args_list]
    assert any("falling back to Tesseract" in str(call) for call in log_calls)
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src uv run python -m pytest tests/test_fetcher.py::test_do_ocr_job_uses_tesseract_backend -v`

Expected: FAIL (backend selection not implemented yet)

**Step 3: Add backend selection logic to do_ocr_job()**

In `src/clerk/fetcher.py`, find the page processing loop in `do_ocr_job()` and update the OCR call:

```python
# Inside the page loop (around line 595-640)
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
                f"falling back to Tesseract: {e}"
            )
            text = self._ocr_with_tesseract(page_image_path)
    else:
        # backend == "tesseract" (default)
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

**Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src uv run python -m pytest tests/test_fetcher.py -k "test_do_ocr_job" -v`

Expected: PASS

**Step 5: Commit**

```bash
git add src/clerk/fetcher.py tests/test_fetcher.py
git commit -m "Add backend selection logic with automatic fallback to Tesseract"
```

---

## Task 6: Add Enhanced Logging

**Files:**
- Modify: `src/clerk/fetcher.py`

**Step 1: Add backend tracking logs to do_ocr_job()**

In `src/clerk/fetcher.py`, add logging at key points:

```python
def do_ocr_job(self, args: tuple, backend: str = "tesseract") -> None:
    """Process OCR for a single document."""
    prefix, meeting, date = args

    # ... existing setup code ...

    # Add at start of processing
    output.log(f"Processing {doc_path} with {backend} backend")

    # ... existing OCR processing ...

    # Add at end of processing (after cleanup)
    output.log(
        f"Completed {doc_path} ({len(pages)} pages in {ocr_duration:.2f}s)"
    )
```

**Step 2: Verify fallback logging is clear**

The fallback logging should already be in place from Task 5:

```python
output.log(
    f"Vision OCR failed for {doc_path} page {page_num}, "
    f"falling back to Tesseract: {e}"
)
```

**Step 3: Test logging manually**

Run a test OCR job and verify logs show backend selection and fallback behavior.

**Step 4: Commit**

```bash
git add src/clerk/fetcher.py
git commit -m "Add enhanced logging for backend selection and processing"
```

---

## Task 7: Document System Dependencies

**Files:**
- Create: `docs/DEVELOPMENT.md`
- Modify: `README.md`

**Step 1: Create DEVELOPMENT.md with system requirements**

Create `docs/DEVELOPMENT.md`:

```markdown
# Development Setup

## System Dependencies

### macOS

For PDF processing with weasyprint, install required system libraries:

```bash
brew install gobject-introspection cairo pango glib
```

**Note:** On Apple Silicon Macs, ensure you're using ARM64 Homebrew (`/opt/homebrew/bin/brew`), not Intel Homebrew (`/usr/local/bin/brew`).

### Vision Framework (macOS only)

To use the Vision Framework OCR backend:

```bash
# Install Python dependencies
pip install pyobjc-framework-Vision pyobjc-framework-Quartz

# Or with uv
uv sync --extra vision
```

**Requirements:**
- macOS 10.15 (Catalina) or later
- Apple Silicon (M1+) recommended for best performance

## Installation

```bash
# Clone repository
git clone https://github.com/civicband/clerk.git
cd clerk

# Install dependencies
uv sync --extra dev --extra pdf --extra vision

# Run tests
PYTHONPATH=src pytest
```

## Running Tests

```bash
# All tests
PYTHONPATH=src pytest

# Specific test file
PYTHONPATH=src pytest tests/test_fetcher.py

# Vision Framework tests (macOS only)
PYTHONPATH=src pytest tests/test_fetcher.py -k vision
```
```

**Step 2: Update README.md with OCR backend documentation**

Add to `README.md`:

```markdown
## OCR Backends

Clerk supports two OCR backends:

### Tesseract (Default)

- **Cross-platform:** Linux, macOS, Windows
- **Languages:** 100+ languages supported
- **Setup:** Requires tesseract binary installed
- **Usage:** `clerk update example.com` (default) or `clerk update example.com --ocr-backend=tesseract`

### Vision Framework (macOS only)

- **Platform:** macOS 10.15+ (M1+ recommended)
- **Performance:** 3-5x faster than Tesseract on Apple Silicon
- **Languages:** Automatic language detection
- **Setup:** `pip install pyobjc-framework-Vision pyobjc-framework-Quartz`
- **Usage:** `clerk update example.com --ocr-backend=vision`

### Automatic Fallback

If Vision Framework is selected but fails (missing dependencies, errors), clerk automatically falls back to Tesseract and logs a warning.

```bash
# Try Vision, fall back to Tesseract if needed
clerk update example.com --ocr-backend=vision
```
```

**Step 3: Commit**

```bash
git add docs/DEVELOPMENT.md README.md
git commit -m "Document system dependencies and OCR backend options"
```

---

## Task 8: Manual Testing

**Files:**
- None (testing only)

**Step 1: Test Tesseract backend (default)**

Run: `clerk update test.example.com`

Expected:
- Processes with Tesseract backend
- Logs show "Processing ... with tesseract backend"
- OCR completes successfully

**Step 2: Test Vision backend on macOS**

Run: `clerk update test.example.com --ocr-backend=vision`

Expected:
- Processes with Vision backend
- Logs show "Processing ... with vision backend"
- OCR completes successfully
- Performance improvement visible

**Step 3: Test fallback behavior**

Temporarily break Vision (e.g., uninstall pyobjc) and run:

Run: `clerk update test.example.com --ocr-backend=vision`

Expected:
- Logs show Vision failure
- Logs show "falling back to Tesseract"
- Processing continues with Tesseract
- No data loss

**Step 4: Compare output quality**

Run same document with both backends and compare:

```bash
clerk update test.example.com --ocr-backend=tesseract
mv ../sites/test.example.com/txt ../sites/test.example.com/txt-tesseract

clerk update test.example.com --ocr-backend=vision
mv ../sites/test.example.com/txt ../sites/test.example.com/txt-vision

diff -r ../sites/test.example.com/txt-tesseract ../sites/test.example.com/txt-vision
```

Expected: Text quality comparable or better with Vision

**Step 5: Document test results**

Add test results to commit message in next step.

---

## Task 9: Final Integration & Cleanup

**Files:**
- Verify all files

**Step 1: Run full test suite**

Run: `PYTHONPATH=src pytest -v`

Expected: All tests pass (or Vision tests skipped on non-macOS)

**Step 2: Run linter**

Run: `uv run ruff check src/clerk`

Expected: No errors

**Step 3: Run type checker**

Run: `uv run mypy src/clerk`

Expected: No new type errors

**Step 4: Review all changes**

Run: `git diff main --stat`

Expected: Changes in expected files only:
- `pyproject.toml`
- `src/clerk/cli.py`
- `src/clerk/fetcher.py`
- `tests/test_cli.py`
- `tests/test_fetcher.py`
- `docs/DEVELOPMENT.md`
- `README.md`

**Step 5: Final commit if needed**

```bash
git add -A
git commit -m "Final cleanup and integration"
```

---

## Completion Checklist

- [ ] pyobjc dependencies added to pyproject.toml
- [ ] --ocr-backend CLI flag working
- [ ] _ocr_with_tesseract() extracted and tested
- [ ] _ocr_with_vision() implemented and tested
- [ ] Backend selection logic with fallback working
- [ ] Enhanced logging in place
- [ ] Documentation updated (DEVELOPMENT.md, README.md)
- [ ] Manual testing completed
- [ ] All tests passing
- [ ] Code linted and type-checked
- [ ] Ready for code review

---

## Next Steps

After implementation complete:

1. **Use @superpowers:requesting-code-review** - Get code review before merging
2. **Use @superpowers:verification-before-completion** - Verify tests pass, build succeeds
3. **Use @superpowers:finishing-a-development-branch** - Decide on merge strategy (PR or direct merge)

## Performance Benchmarking (Optional)

If you want to measure performance improvement:

```bash
# Benchmark Tesseract
time clerk update test.example.com --ocr-backend=tesseract

# Benchmark Vision
time clerk update test.example.com --ocr-backend=vision

# Compare results
```

Expected: Vision 3-5x faster on M2 Mac Mini
