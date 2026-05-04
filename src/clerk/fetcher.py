"""Base fetcher class and utilities for creating custom data fetchers.

This module provides the Fetcher base class that all custom fetchers must extend.
Plugin developers should extend Fetcher and implement the fetch() method.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx
import sqlite_utils
from bs4 import BeautifulSoup

from clerk.ocr_utils import (
    CRITICAL_ERRORS,
    PERMANENT_ERRORS,
    FailureManifest,
    JobState,
    print_progress,
    retry_on_transient,
)
from clerk.output import logger
from clerk.utils import STORAGE_DIR, build_db_from_text_internal, pm

# Optional PDF dependencies
try:
    import pdfkit
    from pdf2image import convert_from_path
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    PdfReader = None
    PdfReadError = Exception
    HTML = None
    pdfkit = None
    convert_from_path = None

NUM_WORKERS = int(os.environ.get("NUM_WORKERS", 10))
# Process PDFs in chunks to avoid "too many open files" error
# 10 workers × 20 pages = 200 file handles (under macOS 256 limit)
PDF_CHUNK_SIZE = int(os.environ.get("PDF_CHUNK_SIZE", 20))

# Timeout for PDF operations that might segfault (in seconds)
PDF_READ_TIMEOUT = int(os.environ.get("PDF_READ_TIMEOUT", 60))
PDF_CONVERT_TIMEOUT = int(os.environ.get("PDF_CONVERT_TIMEOUT", 300))  # 5 minutes


# Detect if running under pytest (tests disable subprocess isolation for mocking)
# In production, ALWAYS use subprocess isolation to prevent segfaults
def _is_test_environment():
    """Check if code is running in test environment."""
    return "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST") is not None


USE_PDF_SUBPROCESS_ISOLATION = not _is_test_environment()


def _pdf_read_worker(doc_path, result_queue):
    """Worker function to read PDF in subprocess (can segfault safely)."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(doc_path)
        total_pages = len(reader.pages)
        result_queue.put(("success", total_pages))
    except Exception as e:
        result_queue.put(("error", type(e).__name__, str(e)))


def _safe_pdf_read(doc_path, timeout=PDF_READ_TIMEOUT):
    """Read PDF in isolated subprocess to protect against segfaults.

    Returns:
        tuple: (success: bool, page_count: int | None, error_msg: str | None)
    """
    import multiprocessing

    result_queue = multiprocessing.Queue()
    process = multiprocessing.Process(target=_pdf_read_worker, args=(doc_path, result_queue))

    try:
        process.start()
        process.join(timeout=timeout)

        if process.is_alive():
            # Timeout - kill the process
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join()
            return (False, None, f"PDF read timed out after {timeout}s")

        # Check exit code (can be None if process never started properly)
        if process.exitcode is None:
            return (False, None, "PDF read process failed to start")

        if process.exitcode != 0:
            # Process crashed (segfault or other signal)
            # Negative exit codes indicate signals (e.g., -11 for SIGSEGV)
            if process.exitcode == -11:
                signal_name = "SIGSEGV"
            elif process.exitcode < 0:
                signal_name = f"signal {abs(process.exitcode)}"
            else:
                signal_name = f"exit code {process.exitcode}"
            return (False, None, f"PDF read crashed with {signal_name}")

        # Process succeeded - get result with timeout to avoid hanging
        try:
            result = result_queue.get(timeout=1)
            if result[0] == "success":
                return (True, result[1], None)
            else:
                # Exception in subprocess
                return (False, None, f"{result[1]}: {result[2]}")
        except Exception:
            # Queue was empty or get timed out
            return (False, None, "PDF read failed with unknown error")

    finally:
        # Clean up resources
        result_queue.close()
        result_queue.join_thread()


def _pdf_convert_worker(doc_path, doc_image_dir_path, chunk_start, chunk_end, prefix, result_queue):
    """Worker function to convert PDF to images in subprocess (can segfault safely)."""
    import tempfile

    try:
        from pdf2image import convert_from_path

        with tempfile.TemporaryDirectory() as temp_path:
            pages = convert_from_path(
                doc_path,
                fmt="png",
                size=(1276, 1648),
                dpi=150,
                output_folder=temp_path,
                first_page=chunk_start,
                last_page=chunk_end,
            )
            # Save pages to final destination
            for idx, page in enumerate(pages):
                page_number = chunk_start + idx
                page_image_path = f"{doc_image_dir_path}/{page_number}.png"
                # Skip if exists (unless it's an agenda - agendas have prefix)
                if not (os.path.exists(page_image_path) and not prefix):
                    page.save(page_image_path, "PNG")

        result_queue.put(("success", len(pages)))
    except Exception as e:
        result_queue.put(("error", type(e).__name__, str(e)))


def _safe_pdf_to_images(
    doc_path, doc_image_dir_path, chunk_start, chunk_end, prefix, timeout=PDF_CONVERT_TIMEOUT
):
    """Convert PDF chunk to images in isolated subprocess to protect against segfaults.

    Returns:
        tuple: (success: bool, page_count: int | None, error_msg: str | None)
    """
    import multiprocessing

    result_queue = multiprocessing.Queue()
    process = multiprocessing.Process(
        target=_pdf_convert_worker,
        args=(doc_path, doc_image_dir_path, chunk_start, chunk_end, prefix, result_queue),
    )

    try:
        process.start()
        process.join(timeout=timeout)

        if process.is_alive():
            # Timeout - kill the process
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join()
            return (False, None, f"PDF conversion timed out after {timeout}s")

        # Check exit code (can be None if process never started properly)
        if process.exitcode is None:
            return (False, None, "PDF conversion process failed to start")

        if process.exitcode != 0:
            # Process crashed (segfault or other signal)
            # Negative exit codes indicate signals (e.g., -11 for SIGSEGV)
            if process.exitcode == -11:
                signal_name = "SIGSEGV"
            elif process.exitcode < 0:
                signal_name = f"signal {abs(process.exitcode)}"
            else:
                signal_name = f"exit code {process.exitcode}"
            return (False, None, f"PDF conversion crashed with {signal_name}")

        # Process succeeded - get result with timeout to avoid hanging
        try:
            result = result_queue.get(timeout=1)
            if result[0] == "success":
                return (True, result[1], None)
            else:
                # Exception in subprocess
                return (False, None, f"{result[1]}: {result[2]}")
        except Exception:
            # Queue was empty or get timed out
            return (False, None, "PDF conversion failed with unknown error")

    finally:
        # Clean up resources
        result_queue.close()
        result_queue.join_thread()


class Fetcher:
    def __init__(
        self, site: dict[str, Any], start_year: int | None = None, all_agendas: bool = False
    ) -> None:
        self.subdomain = site["subdomain"]
        self.start_year = start_year
        self.today = datetime.today()
        self.site = site
        self.all_agendas = all_agendas

        self.ocr_lang = "eng+spa"

        if not self.start_year:
            self.start_year = site["start_year"]

        # TODO: always go one year back and one year forward

        self.storage_dir = STORAGE_DIR
        self.dir_prefix = f"{self.storage_dir}/{self.subdomain}"
        self.minutes_output_dir = f"{self.dir_prefix}/pdfs"
        self.agendas_output_dir = f"{self.dir_prefix}/_agendas/pdfs"
        self.minutes_processed_dir = f"{self.dir_prefix}/processed"
        self.agendas_processed_dir = f"{self.dir_prefix}/_agendas/processed"
        self.docs_output_dir = f"{self.dir_prefix}/_docs/pdfs"
        self.docs_processed_dir = f"{self.dir_prefix}/_docs/processed"
        self.docs_html_dir = f"{self.dir_prefix}/_docs/html"

        self.previous_page_count = site["pages"]

        if not os.path.exists(self.docs_output_dir):
            os.makedirs(self.docs_output_dir)
        if not os.path.exists(self.docs_processed_dir):
            os.makedirs(self.docs_processed_dir)
        if not os.path.exists(self.docs_html_dir):
            os.makedirs(self.docs_html_dir)

        self.db = sqlite_utils.Database(f"{STORAGE_DIR}/{self.subdomain}/meetings.db")

        self.total_events = 0
        self.total_minutes = 0
        self.total_agendas = 0

        self.logger = logger
        self.logger.subdomain = self.subdomain

        self.child_init()

    def child_init(self) -> None:
        # This method exists to be overwritten
        pass

    def assert_fetch_dirs(self) -> None:
        if not os.path.exists(self.minutes_output_dir):
            os.makedirs(self.minutes_output_dir)
        if not os.path.exists(self.agendas_output_dir):
            os.makedirs(self.agendas_output_dir)

    def assert_processed_dirs(self) -> None:
        if not os.path.exists(self.minutes_processed_dir):
            os.makedirs(self.minutes_processed_dir)
        if not os.path.exists(self.agendas_processed_dir):
            os.makedirs(self.agendas_processed_dir)

    def assert_site_db_exists(self) -> None:
        self.db = sqlite_utils.Database(f"{STORAGE_DIR}/{self.subdomain}/meetings.db")
        if not self.db["minutes"].exists():
            _ = self.db["minutes"].create(  # type: ignore[union-attr]  # pyright: ignore[reportUnknownMemberType]
                {
                    "id": str,
                    "meeting": str,
                    "date": str,
                    "page": int,
                    "text": str,
                    "page_image": str,
                },
                pk=("id"),
            )
        if not self.db["agendas"].exists():
            _ = self.db["agendas"].create(  # type: ignore[union-attr]  # pyright: ignore[reportUnknownMemberType]
                {
                    "id": str,
                    "meeting": str,
                    "date": str,
                    "page": int,
                    "text": str,
                    "page_image": str,
                },
                pk=("id"),
            )

    def request(
        self,
        method: str,
        url: str,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
    ) -> httpx.Response | None:
        args_dict = {
            "method": method,
            "url": url,
            "follow_redirects": True,
            "timeout": None,
            "verify": False,
        }
        if headers:
            args_dict["headers"] = headers
        if json:
            args_dict["json"] = json
        if data:
            args_dict["data"] = data
        if cookies:
            args_dict["cookies"] = cookies
        for i in range(3, 0, -1):
            try:
                start_time = time.time()
                response = httpx.request(**args_dict)  # type: ignore[arg-type]
                elapsed_ms = int((time.time() - start_time) * 1000)
                self.logger.log(
                    f"HTTP {method} {url}",
                    method=method,
                    url=url,
                    status_code=response.status_code,
                    duration_ms=elapsed_ms,
                )
                return response
            except httpx.ConnectTimeout:
                self.logger.log(
                    f"Timeout fetching url, trying again {i - 1} more times",
                    level="warning",
                    url=url,
                    retries_remaining=i - 1,
                )
            except httpx.RemoteProtocolError:
                self.logger.log(
                    f"Remote error fetching url, trying again {i - 1} more times",
                    level="warning",
                    url=url,
                    retries_remaining=i - 1,
                )
        return None

    def check_if_exists(self, meeting: str, date: str, kind: str) -> bool:
        if kind == "minutes":
            output_dir = self.minutes_output_dir
            processed_dir = self.minutes_processed_dir
        if kind == "agenda":
            output_dir = self.agendas_output_dir
            processed_dir = self.agendas_processed_dir
        output_path = os.path.join(output_dir, meeting, f"{date}.pdf")
        processed_path_pdf = os.path.join(processed_dir, meeting, f"{date}.pdf")
        processed_path_txt = os.path.join(processed_dir, meeting, f"{date}.txt")
        if (
            os.path.exists(output_path)
            or os.path.exists(processed_path_pdf)
            or os.path.exists(processed_path_txt)
        ):
            return True
        return False

    def simplified_meeting_name(self, body: str) -> str:
        body = (
            body.replace(" ", "")
            .replace("*", "")
            .replace("&", "And")
            .replace("/", "And")
            .replace("SpecialConcurrentMeetingofthe", "")
            .replace("ConcurrentMeetingofthe", "")
            .replace("Meetingofthe", "")
        )
        return body

    def fetch_and_write_pdf(
        self, url: str, kind: str, meeting: str, date: str, headers: dict[str, str] | None = None
    ) -> None:
        if not PDF_SUPPORT:
            raise ImportError(
                "PDF support requires optional dependencies. Install with: pip install civicband-clerk[pdf]"
            )
        # TODO: Assert minutes and agenda output dir exists
        self.assert_fetch_dirs()
        self.logger.meeting = meeting
        if kind == "minutes":
            output_dir = self.minutes_output_dir
        if kind == "agenda":
            output_dir = self.agendas_output_dir
        output_path = os.path.join(output_dir, meeting, f"{date}.pdf")
        try:
            doc_response = self.request("GET", url, headers)
        except httpx.ReadTimeout:
            self.logger.log(
                f"Timeout fetching {url} for {meeting}",
                level="error",
                url=url,
                kind=kind,
            )
            return
        if not doc_response or doc_response.status_code != 200:
            self.logger.log(
                f"Error fetching {url} for {meeting}",
                level="error",
                url=url,
                kind=kind,
                status_code=doc_response.status_code if doc_response else None,
            )
            return
        if "pdf" in doc_response.headers.get("content-type", "").lower():
            self.logger.log(
                "Writing PDF file",
                operation="write_pdf",
                date=date,
                kind=kind,
                output_path=output_path,
            )
            with open(output_path, "wb") as doc_pdf:
                doc_pdf.write(doc_response.content)
        elif "html" in doc_response.headers.get("content-type", "").lower():
            self.logger.log(
                "Converting HTML to PDF",
                operation="html_to_pdf",
                date=date,
                kind=kind,
                output_path=output_path,
            )
            try:
                pdfkit.from_string(doc_response.content, output_path)  # type: ignore
                self.logger.log(
                    "Wrote file using pdfkit",
                    operation="pdfkit_conversion",
                    output_path=output_path,
                )
            except Exception:
                self.logger.log(
                    f"pdfkit HTML->PDF error for {url}",
                    level="warning",
                    url=url,
                )
        else:
            self.logger.log(
                "Unknown content type",
                level="warning",
            )

        # Validate PDF is readable (use subprocess isolation to prevent segfaults)
        if USE_PDF_SUBPROCESS_ISOLATION:
            success, _, error_msg = _safe_pdf_read(output_path, timeout=PDF_READ_TIMEOUT)
            if not success:
                self.logger.log(
                    f"PDF downloaded from {url} failed validation: {error_msg}, removing {output_path}",
                    level="error",
                    url=url,
                    output_path=output_path,
                    error=error_msg,
                )
                if os.path.exists(output_path):
                    os.remove(output_path)
        else:
            # Direct validation (for tests)
            try:
                PdfReader(output_path)  # pyright: ignore[reportOptionalCall]
            except PdfReadError:
                self.logger.log(
                    f"PDF downloaded from {url} errored on read, removing {output_path}",
                    level="error",
                    url=url,
                    output_path=output_path,
                )
                os.remove(output_path)
            except FileNotFoundError:
                self.logger.log(
                    f"PDF from {url} not found at {output_path}",
                    level="error",
                    url=url,
                    output_path=output_path,
                )
            except ValueError:
                self.logger.log(
                    f"PDF downloaded from {url} errored on read, removing {output_path}",
                    level="error",
                    url=url,
                    output_path=output_path,
                )

    def fetch_docs_from_page(
        self, page_number: int, meeting: str, date: str, prefix: str
    ) -> str | None:
        html_dir = os.path.join(self.docs_html_dir, date)

        with open(f"{html_dir}{date}-{page_number}.html", encoding="utf-8") as html_file:
            soup = BeautifulSoup(html_file, "html.parser")
            links = list(soup.find_all("a", href=True))
            for link in links:
                href = link.get("href")
                if not href or not isinstance(href, str):
                    continue
                doc_response = self.request("GET", href)
                if not doc_response:
                    continue
                if "pdf" in doc_response.headers.get("content-type", "").lower():
                    filename_from_resp = (
                        doc_response.headers["content-disposition"].split("filename=")[1].strip('"')
                    )
                    doc_id_hash = {
                        "length": doc_response.headers["content-length"],
                        "filename": filename_from_resp,
                        "url": href,
                    }
                    doc_id = sha256(
                        json.dumps(doc_id_hash, sort_keys=True).encode("utf-8")
                    ).hexdigest()
                    doc_id = doc_id[:12]
                    output_path = os.path.join(self.docs_output_dir, f"{doc_id}.pdf")
                    self.logger.log(
                        "Writing document file",
                        operation="write_document",
                        doc_id=doc_id,
                        filename=filename_from_resp,
                        output_path=output_path,
                    )

                    with open(output_path, "wb") as doc_pdf:
                        doc_pdf.write(doc_response.content)

                    return doc_id
        return None

    def make_html_from_pdf(self, date: str, doc_path: str) -> None:
        # TODO: assert
        html_dir = os.path.join(self.docs_html_dir, date)
        if not os.path.exists(html_dir):
            os.makedirs(html_dir)
        subprocess.check_output(
            [
                "pdftohtml",
                "-c",
                doc_path,
                html_dir,
            ],
            stderr=subprocess.DEVNULL,
        )

    def ocr(self, backend: str = "tesseract") -> None:
        """Run OCR on both minutes and agendas.

        Args:
            backend: OCR backend to use ('tesseract' or 'vision')
        """
        st = time.time()
        self.logger.log(
            "Starting OCR for all documents",
            operation="ocr_start",
            backend=backend,
        )
        self.do_ocr(backend=backend)
        self.do_ocr(prefix="/_agendas", backend=backend)
        et = time.time()
        elapsed_time = et - st
        self.logger.log(
            f"Total OCR execution time: {elapsed_time:.2f} seconds",
            operation="ocr_complete",
            backend=backend,
            duration_seconds=round(elapsed_time, 2),
        )

    def transform(self) -> None:
        build_db_from_text_internal(self.subdomain)
        self.assert_site_db_exists()
        try:
            agendas_count = self.db["agendas"].count
        except sqlite3.OperationalError:
            agendas_count = 0
        minutes_count = self.db["minutes"].count
        page_count = agendas_count + minutes_count
        self.logger.log(
            f"Processed {page_count} pages, {agendas_count} agendas, {minutes_count} minutes. Formerly {self.previous_page_count} pages processed.",
            operation="transform_complete",
            pages=page_count,
            agendas=agendas_count,
            minutes=minutes_count,
            previous_pages=self.previous_page_count,
        )

    def do_ocr(self, prefix: str = "", backend: str = "tesseract") -> None:
        """Run OCR on all PDFs in the directory.

        Args:
            prefix: Directory prefix (e.g., "" for minutes, "/_agendas" for agendas)
            backend: OCR backend to use ('tesseract' or 'vision')
        """

        # Generate unique job ID
        job_id = f"ocr_{int(time.time())}"
        self.logger.job_id = job_id

        # Setup directories
        self.images_dir = f"{self.dir_prefix}{prefix}/images"
        pdf_dir = f"{self.dir_prefix}{prefix}/pdfs"
        txt_dir = f"{self.dir_prefix}{prefix}/txt"
        processed_dir = f"{self.dir_prefix}{prefix}/processed"

        if not os.path.exists(processed_dir):
            os.makedirs(processed_dir)

        if not os.path.exists(f"{pdf_dir}"):
            self.logger.log(
                f"No PDFs found in {pdf_dir}",
                operation="ocr_skip",
                pdf_dir=pdf_dir,
                prefix=prefix,
            )
            return

        # Build job list
        directories = [
            directory for directory in sorted(os.listdir(pdf_dir)) if directory != ".DS_Store"
        ]
        jobs = []
        for meeting in directories:
            meeting_images_dir = f"{self.images_dir}/{meeting}"
            meeting_txt_dir = f"{txt_dir}/{meeting}"
            if not os.path.exists(meeting_images_dir):
                os.makedirs(meeting_images_dir)
            if not os.path.exists(meeting_txt_dir):
                os.makedirs(meeting_txt_dir)
            for document in sorted(os.listdir(f"{pdf_dir}/{meeting}")):
                if not document.endswith(".pdf"):
                    continue
                date = document.replace(".pdf", "")
                if not os.path.exists(f"{meeting_images_dir}/{date}"):
                    os.makedirs(f"{meeting_images_dir}/{date}")
                if not os.path.exists(f"{meeting_txt_dir}/{date}"):
                    os.makedirs(f"{meeting_txt_dir}/{date}")
                if not os.path.exists(f"{self.dir_prefix}{prefix}/processed/{meeting}"):
                    os.makedirs(f"{self.dir_prefix}{prefix}/processed/{meeting}")

                jobs.append((prefix, meeting, date))

        if not jobs:
            self.logger.log(
                f"No PDF documents to process in {pdf_dir}",
                operation="ocr_skip",
                pdf_dir=pdf_dir,
                prefix=prefix,
            )
            return

        # Initialize job state and failure manifest
        state = JobState(job_id=job_id, total_documents=len(jobs))
        manifest_path = f"{self.dir_prefix}/ocr_failures_{job_id}.jsonl"
        manifest = FailureManifest(manifest_path)

        self.logger.log(
            "OCR job started",
            operation="ocr_job_start",
            job_id=job_id,
            total_documents=len(jobs),
            prefix=prefix,
            backend=backend,
        )

        # Process jobs with thread pool
        with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
            future_to_job = {
                executor.submit(self.do_ocr_job, job, manifest, job_id, backend): job
                for job in jobs
            }

            for future in concurrent.futures.as_completed(future_to_job):
                job = future_to_job[future]
                try:
                    future.result()
                    state.completed += 1
                except PERMANENT_ERRORS:
                    state.failed += 1
                except CRITICAL_ERRORS as e:
                    manifest.close()
                    self.logger.log(
                        "Critical error, halting OCR job",
                        operation="ocr_critical_error",
                        error_class=e.__class__.__name__,
                        error_message=str(e),
                        level="error",
                    )
                    raise
                except Exception as exc:
                    # Catch-all for unexpected errors
                    self.logger.log(
                        f"{job!r} generated an exception: {exc}",
                        operation="ocr_unexpected_error",
                        error_message=str(exc),
                        level="error",
                    )
                    state.failed += 1

                # Print progress every 5 documents
                processed = state.completed + state.failed + state.skipped
                if processed % 5 == 0 or processed == state.total_documents:
                    print_progress(state, self.subdomain)

        manifest.close()

        # Log job completion
        elapsed = time.time() - state.start_time
        self.logger.log(
            "OCR job completed",
            operation="ocr_job_complete",
            backend=backend,
            completed=state.completed,
            failed=state.failed,
            skipped=state.skipped,
            total_documents=state.total_documents,
            duration_seconds=round(elapsed, 2),
            prefix=prefix,
        )

        # Print final summary
        self.logger.log(
            f"OCR job {job_id} completed: {state.completed} succeeded, "
            f"{state.failed} failed, {state.skipped} skipped "
            f"(total: {state.total_documents} documents in {elapsed:.1f}s)",
        )

        if state.failed > 0:
            self.logger.log(
                f"Failure manifest written to: {manifest_path}",
                manifest_path=manifest_path,
                failed_count=state.failed,
            )

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
                "-l",
                self.ocr_lang,  # "eng+spa"
                "--dpi",
                "150",
                "--oem",
                "1",  # LSTM engine
                str(image_path),
                "stdout",
            ],
            stderr=subprocess.DEVNULL,
        )
        return text.decode("utf-8")

    @retry_on_transient(max_attempts=3, delay_seconds=2)
    def do_ocr_job(
        self,
        job: tuple[str, str, str],
        manifest: FailureManifest | None,
        job_id: str,
        backend: str = "tesseract",
        run_id: str | None = None,
    ) -> None:
        """Process a single PDF document through OCR pipeline.

        Args:
            job: Tuple of (prefix, meeting, date)
            manifest: FailureManifest for recording failures (optional)
            job_id: RQ job identifier for correlation with worker logs
            backend: OCR backend to use ('tesseract' or 'vision')
            run_id: Pipeline run identifier for correlation across jobs (optional)
        """
        self.logger.job_id = job_id
        self.logger.run_id = run_id
        self.logger.backend = backend
        if not PDF_SUPPORT:
            raise ImportError(
                "PDF support requires optional dependencies. Install with: pip install civicband-clerk[pdf]"
            )

        st = time.time()
        prefix = job[0]
        meeting = job[1]
        date = job[2]

        self.logger.meeting = meeting
        self.logger.date = date

        # Build paths early for diagnostics
        doc_path = f"{self.dir_prefix}{prefix}/pdfs/{meeting}/{date}.pdf"
        doc_image_dir_path = f"{self.dir_prefix}{prefix}/images/{meeting}/{date}"
        doc_txt_dir_path = f"{self.dir_prefix}{prefix}/txt/{meeting}/{date}"

        # Log job start with all context immediately
        self.logger.log(
            "OCR job started",
            operation="ocr_job_start",
            prefix=prefix,
            doc_path=doc_path,
            subprocess_isolation_enabled=USE_PDF_SUBPROCESS_ISOLATION,
        )

        try:
            # Log before file system checks
            self.logger.log(
                "Checking PDF file existence",
                operation="check_file_exists",
                doc_path=doc_path,
            )

            # Check if PDF file exists before attempting to read
            if not os.path.exists(doc_path):
                self.logger.log(
                    f"PDF file not found: {doc_path}. "
                    "Fetch job may have failed or file was deleted.",
                    level="error",
                    doc_path=doc_path,
                    error_type="missing_pdf",
                )
                return  # Skip this job without raising exception

            # Log file metadata before reading
            file_size = os.path.getsize(doc_path)

            # Check for empty/corrupted PDF before attempting to read
            if file_size == 0:
                self.logger.log(
                    f"Skipping empty PDF file (0 bytes): {doc_path}. "
                    "File likely from failed download. Manual cleanup required.",
                    level="error",
                    doc_path=doc_path,
                    file_size=0,
                    error_type="empty_pdf",
                )
                return  # Skip this job without raising exception

            # PDF reading with timing (isolated subprocess to prevent segfaults in production)
            read_st = time.time()

            self.logger.log(
                "About to read PDF",
                operation="pdf_read_start",
                doc_path=doc_path,
                file_size_mb=round(file_size / (1024 * 1024), 2),
                subprocess_isolation=USE_PDF_SUBPROCESS_ISOLATION,
            )

            if USE_PDF_SUBPROCESS_ISOLATION:
                success, total_pages, error_msg = _safe_pdf_read(doc_path, timeout=PDF_READ_TIMEOUT)
            else:
                # Direct call (for tests or when subprocess isolation is disabled)
                try:
                    reader = PdfReader(doc_path)  # pyright: ignore[reportOptionalCall]
                    total_pages = len(reader.pages)
                    success = True
                    error_msg = None
                except Exception as e:
                    success = False
                    total_pages = None
                    error_msg = str(e)

            if not success:
                # Record failure in manifest if available
                if manifest:
                    manifest.record_failure(
                        job_id=job_id,
                        document_path=doc_path,
                        meeting=meeting,
                        date=date,
                        error_type="permanent",
                        error_class="PdfReadError",  # Match exception name for consistency
                        error_message=error_msg or "Unknown error",
                        retry_count=0,
                    )

                self.logger.log(
                    f"{doc_path} failed to read: {error_msg}. "
                    "PDF may be corrupted or too large. Skipping this document.",
                    level="error",
                    doc_path=doc_path,
                    error_message=error_msg,
                    error_type="corrupted_pdf",
                )
                return  # Skip this job without raising exception

            # At this point, total_pages is guaranteed to be an int (not None)
            assert total_pages is not None, "total_pages should not be None after successful read"

            self.logger.log(
                "PDF read successfully",
                operation="pdf_read_complete",
                page_count=total_pages,
                duration_ms=int((time.time() - read_st) * 1000),
            )

            # Image conversion with timing
            conv_st = time.time()

            self.logger.log(
                "Starting PDF to images conversion",
                operation="pdf_convert_start",
                doc_path=doc_path,
                total_pages=total_pages,
                chunk_size=PDF_CHUNK_SIZE,
                subprocess_isolation=USE_PDF_SUBPROCESS_ISOLATION,
            )

            # Create images directory if it doesn't exist
            # Handles both minutes (no prefix) and agendas (prefix="/_agendas")
            os.makedirs(doc_image_dir_path, exist_ok=True)

            # Create txt directory if it doesn't exist
            # Handles both minutes (no prefix) and agendas (prefix="/_agendas")
            os.makedirs(doc_txt_dir_path, exist_ok=True)

            # Convert PDF to images in chunks (isolated subprocess to prevent segfaults in production)
            conversion_failed = False
            for chunk_start in range(1, total_pages + 1, PDF_CHUNK_SIZE):
                chunk_end = min(chunk_start + PDF_CHUNK_SIZE - 1, total_pages)

                if USE_PDF_SUBPROCESS_ISOLATION:
                    self.logger.log(
                        f"Using subprocess isolation for PDF to images (pages {chunk_start}-{chunk_end})",
                        operation="pdf_convert_isolated",
                        chunk_start=chunk_start,
                        chunk_end=chunk_end,
                    )
                    success, _, error_msg = _safe_pdf_to_images(
                        doc_path,
                        doc_image_dir_path,
                        chunk_start,
                        chunk_end,
                        prefix,
                        timeout=PDF_CONVERT_TIMEOUT,
                    )
                elif PDF_SUPPORT:
                    # Direct call (for tests or when subprocess isolation is disabled)
                    try:
                        with tempfile.TemporaryDirectory() as temp_path:
                            pages = convert_from_path(  # pyright: ignore[reportOptionalCall]
                                doc_path,
                                fmt="png",
                                size=(1276, 1648),
                                dpi=150,
                                output_folder=temp_path,
                                first_page=chunk_start,
                                last_page=chunk_end,
                            )
                            for idx, page in enumerate(pages):
                                page_number = chunk_start + idx
                                page_image_path = f"{doc_image_dir_path}/{page_number}.png"
                                if os.path.exists(page_image_path) and not prefix:
                                    continue
                                page.save(page_image_path, "PNG")
                        success = True
                        error_msg = None
                    except Exception as e:
                        success = False
                        error_msg = str(e)

                if not success:
                    conversion_failed = True
                    # Record failure in manifest if available
                    if manifest:
                        manifest.record_failure(
                            job_id=job_id,
                            document_path=doc_path,
                            meeting=meeting,
                            date=date,
                            error_type="permanent",
                            error_class="PdfProcessingError",  # Generic error for PDF conversion issues
                            error_message=error_msg or "Unknown error",
                            retry_count=0,
                        )

                    self.logger.log(
                        f"{doc_path} failed to process (chunk {chunk_start}-{chunk_end}): {error_msg}. "
                        "PDF conversion to images failed. Skipping this document.",
                        level="error",
                        doc_path=doc_path,
                        error_message=error_msg,
                        error_type="pdf_processing_failed",
                        chunk_start=chunk_start,
                        chunk_end=chunk_end,
                    )
                    break

            if conversion_failed:
                return  # Skip this job without raising exception

            self.logger.log(
                "Image conversion completed",
                operation="pdf_to_images",
                page_count=total_pages,
                duration_ms=int((time.time() - conv_st) * 1000),
            )

            # OCR with timing
            ocr_st = time.time()

            self.logger.log(
                "Starting OCR processing",
                operation="ocr_start",
                doc_path=doc_path,
                total_pages=total_pages,
            )

            pages_processed = 0
            for page_image in os.listdir(f"{doc_image_dir_path}"):
                page_image_path = f"{doc_image_dir_path}/{page_image}"
                remote_storage_path = f"/{self.subdomain}{prefix}/{meeting}/{date}/{page_image}"
                txt_filename = page_image.replace(".png", ".txt")
                txt_filepath = f"{doc_txt_dir_path}/{txt_filename}"

                if not os.path.exists(txt_filepath):
                    # Log every 10th page to track progress
                    if pages_processed % 10 == 0:
                        self.logger.log(
                            f"OCR progress: processing page {pages_processed}/{total_pages}",
                            operation="ocr_progress",
                            pages_processed=pages_processed,
                            total_pages=total_pages,
                            current_page=page_image,
                        )

                    try:
                        if backend == "paddleocr":
                            text = _ocr_with_paddleocr(Path(page_image_path))
                        else:
                            text = self._ocr_with_tesseract(Path(page_image_path))

                        with open(txt_filepath, "w", encoding="utf-8") as textfile:
                            textfile.write(text)
                        pages_processed += 1
                    except Exception as e:
                        self.logger.log(
                            f"error processing {page_image_path}, {e}",
                            level="error",
                            page_image_path=page_image_path,
                            error_message=str(e),
                        )

                    pm.hook.upload_static_file(
                        file_path=page_image_path, storage_path=remote_storage_path
                    )

                if page_image.endswith(".txt"):
                    continue

            self.logger.log(
                "OCR completed",
                operation="ocr_complete",
                page_count=total_pages,
                duration_ms=int((time.time() - ocr_st) * 1000),
            )

            # Cleanup
            processed_path = f"{self.dir_prefix}{prefix}/processed/{meeting}/{date}.txt"
            os.makedirs(os.path.dirname(processed_path), exist_ok=True)
            with open(processed_path, "a"):
                os.utime(processed_path, None)
            remote_pdf_path = f"{self.subdomain}{prefix}/_pdfs/{meeting}/{date}.pdf"
            pm.hook.upload_static_file(file_path=doc_path, storage_path=remote_pdf_path)
            os.remove(doc_path)
            shutil.rmtree(doc_image_dir_path)

            # Completion logging with full processing stats
            total_duration = time.time() - st
            self.logger.log(
                f"Document completed: {total_pages} pages in {total_duration:.2f}s",
                operation="document_complete",
                page_count=total_pages,
                duration_seconds=round(total_duration, 2),
                prefix=prefix,
            )

        except PERMANENT_ERRORS as e:
            if manifest:
                manifest.record_failure(
                    job_id=job_id,
                    document_path=doc_path,
                    meeting=meeting,
                    date=date,
                    error_type="permanent",
                    error_class=e.__class__.__name__,
                    error_message=str(e),
                    retry_count=0,  # Already retried by decorator if transient
                )
            self.logger.log(
                "Document failed with permanent error",
                operation="document_permanent_error",
                error_class=e.__class__.__name__,
                error_message=str(e),
                level="error",
            )
            return  # Skip and continue

        except CRITICAL_ERRORS as e:
            self.logger.log(
                "Critical error in OCR job",
                operation="document_critical_error",
                error_class=e.__class__.__name__,
                error_message=str(e),
                level="error",
            )
            raise  # Fail fast

    def fetch_events(self) -> None:
        """Subclasses must override this to fetch meeting data."""
        raise NotImplementedError("Subclasses must implement fetch_events()")


def get_fetcher(site, all_years=False, all_agendas=False) -> Fetcher:  # type: ignore
    start_year = site["start_year"]
    fetcher_class = None
    try:
        start_year = datetime.strptime(site["last_updated"], "%Y-%m-%dT%H:%M:%S").year
    except TypeError:
        start_year = site["start_year"]
    if all_years:
        start_year = site["start_year"]
    fetcher_class = pm.hook.fetcher_class(label=site["scraper"])

    fetcher_class = list(filter(None, fetcher_class))
    if len(fetcher_class):
        fetcher_class = fetcher_class[0]

    if fetcher_class:
        return fetcher_class(site, start_year, all_agendas)  # type: ignore[no-any-return, operator]  # pyright: ignore[reportCallIssue]
    if site["scraper"] == "custom":
        import importlib

        module_path = f"fetchers.custom.{site['subdomain'].replace('.', '_')}"
        fetcher = importlib.import_module(module_path)
        return fetcher.custom_fetcher(site, start_year, all_agendas)  # type: ignore[no-any-return]


def _ocr_with_paddleocr(image_path: Path) -> str:
    """Perform OCR using PaddleOCR (PP-OCRv4).

    PaddleOCR is an open-source OCR toolkit that excels at:
    - Document layout analysis (tables, multi-column text)
    - Handling skewed/rotated text
    - Better accuracy on low-quality scans
    - CPU-friendly inference with small models

    Args:
        image_path: Path to image file to OCR

    Returns:
        Extracted text string

    Raises:
        ImportError: If paddleocr package is not installed
        RuntimeError: If OCR processing fails
    """
    try:
        from paddleocr import PaddleOCR  # pyright: ignore[reportMissingImports]
    except ImportError:
        raise ImportError(
            "PaddleOCR backend requires the 'paddleocr' package. "
            "Install with: pip install paddleocr"
        )

    # Initialize PaddleOCR with CPU-friendly settings
    # use_angle_cls: Enable text orientation classification
    # lang: 'en' for English documents
    # use_gpu: False for CPU-only workers
    # show_log: False to reduce noise
    ocr = PaddleOCR(
        use_angle_cls=True,
        lang="en",
        use_gpu=False,
        show_log=False,
    )

    try:
        # Run OCR on the image
        # result format: [[box, (text, confidence)], ...]
        result = ocr.ocr(str(image_path), cls=True)

        if not result or not result[0]:
            logger.debug("No text detected in image: %s", image_path)
            return ""

        # Extract text from all detected boxes
        # result[0] is the list of detections for the first (only) image
        lines = []
        for line in result[0]:
            text = line[1][0]  # Extract text from (text, confidence) tuple
            lines.append(text)

        return "\n".join(lines)

    except Exception as e:
        logger.error("PaddleOCR failed on %s: %s", image_path, str(e))
        raise RuntimeError(f"PaddleOCR processing failed: {e}") from e
