import concurrent.futures
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import ParseError

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
from clerk.output import log
from clerk.utils import STORAGE_DIR, build_db_from_text_internal, pm

logger = logging.getLogger(__name__)

# Optional PDF dependencies
try:
    import pdfkit
    from pdf2image import convert_from_path
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    from weasyprint import HTML

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
            self.db["minutes"].create(  # type: ignore[union-attr]
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
            self.db["agendas"].create(  # type: ignore[union-attr]
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
                logger.info(
                    "HTTP %s %s status=%d time_ms=%d",
                    method,
                    url,
                    response.status_code,
                    elapsed_ms,
                )
                return response
            except httpx.ConnectTimeout:
                log(
                    f"Timeout fetching url, trying again {i - 1} more times",
                    subdomain=self.subdomain,
                    level="warning",
                    url=url,
                )
            except httpx.RemoteProtocolError:
                log(
                    f"Remote error fetching url, trying again {i - 1} more times",
                    subdomain=self.subdomain,
                    level="warning",
                    url=url,
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
                "PDF support requires optional dependencies. Install with: pip install clerk[pdf]"
            )
        # TODO: Assert minutes and agenda output dir exists
        self.assert_fetch_dirs()
        if kind == "minutes":
            output_dir = self.minutes_output_dir
        if kind == "agenda":
            output_dir = self.agendas_output_dir
        output_path = os.path.join(output_dir, meeting, f"{date}.pdf")
        try:
            doc_response = self.request("GET", url, headers)
        except httpx.ReadTimeout:
            log(f"Timeout fetching {url} for {meeting}", subdomain=self.subdomain, level="error")
            return
        if not doc_response or doc_response.status_code != 200:
            log(f"Error fetching {url} for {meeting}", subdomain=self.subdomain, level="error")
            return
        if "pdf" in doc_response.headers.get("content-type", "").lower():
            log(f"Writing file {output_path}, meeting: {meeting}", subdomain=self.subdomain)
            with open(output_path, "wb") as doc_pdf:
                doc_pdf.write(doc_response.content)
        elif "html" in doc_response.headers.get("content-type", "").lower():
            log(f"HTML -> PDF: {output_path}, meeting: {meeting}", subdomain=self.subdomain)
            try:
                HTML(string=doc_response.content).write_pdf(output_path)
            except ParseError:
                log(
                    f"WeasyPrint HTML->PDF error for {url}, trying pdfkit",
                    subdomain=self.subdomain,
                    level="warning",
                )
                pdfkit.from_string(doc_response.content, output_path)
                log(f"Wrote file {output_path}, meeting: {meeting}", subdomain=self.subdomain)
        else:
            try:
                log(
                    f"Unknown content type {doc_response.headers['content-type']}, meeting: {meeting}",
                    subdomain=self.subdomain,
                    level="warning",
                )
            except KeyError:
                log(
                    f"Couldn't find content-type headers for {url}",
                    subdomain=self.subdomain,
                    level="error",
                )
        try:
            PdfReader(output_path)
        except PdfReadError:
            log(
                f"PDF downloaded from {url} errored on read, removing {output_path}",
                subdomain=self.subdomain,
                level="error",
            )
            os.remove(output_path)
        except FileNotFoundError:
            log(
                f"PDF from {url} not found at {output_path}",
                subdomain=self.subdomain,
                level="error",
            )
        except ValueError:
            log(
                f"PDF downloaded from {url} errored on read, removing {output_path}",
                subdomain=self.subdomain,
                level="error",
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
                    log(f"Writing file {output_path}", subdomain=self.subdomain)

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
        self.do_ocr(backend=backend)
        self.do_ocr(prefix="/_agendas", backend=backend)
        et = time.time()
        elapsed_time = et - st
        log(
            f"Total OCR execution time: {elapsed_time:.2f} seconds",
            subdomain=self.subdomain,
            elapsed_time=f"{elapsed_time:.2f}",
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
        log(
            f"Processed {page_count} pages, {agendas_count} agendas, {minutes_count} minutes. Formerly {self.previous_page_count} pages processed.",
            subdomain=self.subdomain,
            pages=page_count,
            agendas=agendas_count,
            minutes=minutes_count,
        )

    def do_ocr(self, prefix: str = "", backend: str = "tesseract") -> None:
        """Run OCR on all PDFs in the directory.

        Args:
            prefix: Directory prefix (e.g., "" for minutes, "/_agendas" for agendas)
            backend: OCR backend to use ('tesseract' or 'vision')
        """
        # Generate unique job ID
        job_id = f"ocr_{int(time.time())}"

        # Setup directories
        self.images_dir = f"{self.dir_prefix}{prefix}/images"
        pdf_dir = f"{self.dir_prefix}{prefix}/pdfs"
        txt_dir = f"{self.dir_prefix}{prefix}/txt"
        processed_dir = f"{self.dir_prefix}{prefix}/processed"

        if not os.path.exists(processed_dir):
            os.makedirs(processed_dir)

        if not os.path.exists(f"{pdf_dir}"):
            log(f"No PDFs found in {pdf_dir}", subdomain=self.subdomain)
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
            log(f"No PDF documents to process in {pdf_dir}", subdomain=self.subdomain)
            return

        # Initialize job state and failure manifest
        state = JobState(job_id=job_id, total_documents=len(jobs))
        manifest_path = f"{self.dir_prefix}/ocr_failures_{job_id}.jsonl"
        manifest = FailureManifest(manifest_path)

        log(
            "OCR job started",
            subdomain=self.subdomain,
            job_id=job_id,
            total_documents=len(jobs),
            prefix=prefix,
        )

        # Process jobs with thread pool
        with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
            future_to_job = {
                executor.submit(self.do_ocr_job, job, manifest, job_id, backend): job for job in jobs
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
                    log(
                        "Critical error, halting OCR job",
                        subdomain=self.subdomain,
                        job_id=job_id,
                        error_class=e.__class__.__name__,
                        error_message=str(e),
                        level="error",
                    )
                    raise
                except Exception as exc:
                    # Catch-all for unexpected errors
                    log(
                        f"{job!r} generated an exception: {exc}",
                        subdomain=self.subdomain,
                        job_id=job_id,
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
        log(
            "OCR job completed",
            subdomain=self.subdomain,
            job_id=job_id,
            completed=state.completed,
            failed=state.failed,
            skipped=state.skipped,
            duration_seconds=int(elapsed),
        )

        # Print final summary
        log(
            f"OCR job {job_id} completed: {state.completed} succeeded, "
            f"{state.failed} failed, {state.skipped} skipped "
            f"(total: {state.total_documents} documents in {elapsed:.1f}s)",
            subdomain=self.subdomain,
        )

        if state.failed > 0:
            log(f"Failure manifest written to: {manifest_path}", subdomain=self.subdomain)

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

    @retry_on_transient(max_attempts=3, delay_seconds=2)
    def do_ocr_job(
        self, job: tuple[str, str, str], manifest: FailureManifest, job_id: str, backend: str = "tesseract"
    ) -> None:
        """Process a single PDF document through OCR pipeline.

        Args:
            job: Tuple of (prefix, meeting, date)
            manifest: FailureManifest for recording failures
            job_id: Unique job identifier for logging
            backend: OCR backend to use ('tesseract' or 'vision')
        """
        if not PDF_SUPPORT:
            raise ImportError(
                "PDF support requires optional dependencies. Install with: pip install clerk[pdf]"
            )

        st = time.time()
        prefix = job[0]
        meeting = job[1]
        date = job[2]

        log(
            "Processing document",
            subdomain=self.subdomain,
            job_id=job_id,
            meeting=meeting,
            date=date,
        )

        try:
            doc_path = f"{self.dir_prefix}{prefix}/pdfs/{meeting}/{date}.pdf"
            doc_image_dir_path = f"{self.dir_prefix}{prefix}/images/{meeting}/{date}"

            # PDF reading with timing
            read_st = time.time()
            try:
                reader = PdfReader(doc_path)
                total_pages = len(reader.pages)
            except Exception as e:
                log(f"{doc_path} failed to read: {e}", subdomain=self.subdomain, level="error")
                raise

            log(
                "PDF read",
                subdomain=self.subdomain,
                operation="pdf_read",
                meeting=meeting,
                date=date,
                page_count=total_pages,
                duration_ms=int((time.time() - read_st) * 1000),
            )

            # Image conversion with timing
            conv_st = time.time()
            try:
                for chunk_start in range(1, total_pages + 1, PDF_CHUNK_SIZE):
                    chunk_end = min(chunk_start + PDF_CHUNK_SIZE - 1, total_pages)
                    with tempfile.TemporaryDirectory() as path:
                        pages = convert_from_path(
                            doc_path,
                            fmt="png",
                            size=(1276, 1648),
                            dpi=150,
                            output_folder=path,
                            first_page=chunk_start,
                            last_page=chunk_end,
                        )
                        for idx, page in enumerate(pages):
                            page_number = chunk_start + idx
                            page_image_path = f"{doc_image_dir_path}/{page_number}.png"
                            if os.path.exists(page_image_path) and not prefix:
                                continue
                            page.save(page_image_path, "PNG")
            except Exception as e:
                log(f"{doc_path} failed to process: {e}", subdomain=self.subdomain, level="error")
                raise

            log(
                "Image conversion",
                subdomain=self.subdomain,
                operation="pdf_to_images",
                meeting=meeting,
                date=date,
                duration_ms=int((time.time() - conv_st) * 1000),
            )

            # OCR with timing
            ocr_st = time.time()
            for page_image in os.listdir(f"{doc_image_dir_path}"):
                page_image_path = f"{doc_image_dir_path}/{page_image}"
                remote_storage_path = f"/{self.subdomain}{prefix}/{meeting}/{date}/{page_image}"
                txt_filename = page_image.replace(".png", ".txt")
                txt_filepath = f"{self.dir_prefix}{prefix}/txt/{meeting}/{date}/{txt_filename}"

                if not os.path.exists(txt_filepath):
                    try:
                        text = self._ocr_with_tesseract(Path(page_image_path))

                        with open(txt_filepath, "w", encoding="utf-8") as textfile:
                            textfile.write(text)
                    except Exception as e:
                        log(
                            f"error processing {page_image_path}, {e}",
                            subdomain=self.subdomain,
                            level="error",
                        )

                    pm.hook.upload_static_file(
                        file_path=page_image_path, storage_path=remote_storage_path
                    )

                if page_image.endswith(".txt"):
                    continue

            log(
                "OCR completed",
                subdomain=self.subdomain,
                operation="tesseract",
                meeting=meeting,
                date=date,
                page_count=total_pages,
                duration_ms=int((time.time() - ocr_st) * 1000),
            )

            # Cleanup
            processed_path = f"{self.dir_prefix}{prefix}/processed/{meeting}/{date}.txt"
            with open(processed_path, "a"):
                os.utime(processed_path, None)
            remote_pdf_path = f"{self.subdomain}{prefix}/_pdfs/{meeting}/{date}.pdf"
            pm.hook.upload_static_file(file_path=doc_path, storage_path=remote_pdf_path)
            os.remove(doc_path)
            shutil.rmtree(doc_image_dir_path)

            log(
                "Document completed",
                subdomain=self.subdomain,
                job_id=job_id,
                meeting=meeting,
                date=date,
                total_duration_ms=int((time.time() - st) * 1000),
            )

        except PERMANENT_ERRORS as e:
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
            log(
                "Document failed",
                subdomain=self.subdomain,
                job_id=job_id,
                meeting=meeting,
                date=date,
                error_class=e.__class__.__name__,
                error_message=str(e),
                level="error",
            )
            return  # Skip and continue

        except CRITICAL_ERRORS as e:
            log(
                "Critical error",
                subdomain=self.subdomain,
                job_id=job_id,
                error_class=e.__class__.__name__,
                error_message=str(e),
                level="error",
            )
            raise  # Fail fast

    def fetch_events(self) -> None:
        """Subclasses must override this to fetch meeting data."""
        raise NotImplementedError("Subclasses must implement fetch_events()")
