import concurrent.futures
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime
from hashlib import sha256
from typing import Any
from xml.etree.ElementTree import ParseError

import click
import httpx
import sqlite_utils
from bs4 import BeautifulSoup

from clerk.utils import STORAGE_DIR, build_db_from_text_internal, pm

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
        for i in range(3):
            try:
                return httpx.request(**args_dict)  # type: ignore[arg-type]
            except httpx.ConnectTimeout:
                self.message_print(f"Timeout fetching url, trying again {i - 1} more times, {url}")
            except httpx.RemoteProtocolError:
                self.message_print(
                    f"Remote error fetching url, trying again {i - 1} more times, {url}"
                )
        return None

    def message_print(self, message: str) -> None:
        click.echo(click.style(f"{self.subdomain}: ", fg="cyan") + message)

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
            self.message_print(click.style(f"Timeout fetching {url} for {meeting}", fg="red"))
            return
        if not doc_response or doc_response.status_code != 200:
            self.message_print(
                click.style(
                    f"Error fetching {url} for {meeting}",
                    fg="red",
                )
            )
            return
        if "pdf" in doc_response.headers.get("content-type", "").lower():
            self.message_print(f"Writing file {output_path}, meeting: {meeting}")
            with open(output_path, "wb") as doc_pdf:
                doc_pdf.write(doc_response.content)
        elif "html" in doc_response.headers.get("content-type", "").lower():
            self.message_print(f"HTML -> PDF: {output_path}, meeting: {meeting}")
            try:
                HTML(string=doc_response.content).write_pdf(output_path)
            except ParseError:
                self.message_print(f"WeasyPrint HTML->PDF error for {url}, trying pdfkit")
                pdfkit.from_string(doc_response.content, output_path)
                self.message_print(f"Wrote file {output_path}, meeting: {meeting}")
        else:
            try:
                self.message_print(
                    f"Unknown content type {doc_response.headers['content-type']}, meeting: {meeting}"
                )
            except KeyError:
                self.message_print(
                    click.style(f"Couldn't find content-type headers for {url}", fg="red")
                )
        try:
            PdfReader(output_path)
        except PdfReadError:
            self.message_print(
                click.style(
                    f"PDF downloaded from {url} errored on read, removing {output_path}",
                    fg="red",
                )
            )
            os.remove(output_path)
        except FileNotFoundError:
            self.message_print(click.style(f"PDF from {url} not found at {output_path}", fg="red"))
        except ValueError:
            self.message_print(
                click.style(
                    f"PDF downloaded from {url} errored on read, removing {output_path}",
                    fg="red",
                )
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
                    self.message_print(f"Writing file {output_path}")

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

    def ocr(self) -> None:
        # TODO: Assert correct directories exist for minutes and agendas
        # TODO: This should be a "transform" function
        st = time.time()
        self.do_ocr()
        self.do_ocr(prefix="/_agendas")
        et = time.time()
        elapsed_time = et - st
        self.message_print(f"OCR execution time: {elapsed_time} seconds")

    def transform(self) -> None:
        build_db_from_text_internal(self.subdomain)
        self.assert_site_db_exists()
        try:
            agendas_count = self.db["agendas"].count
        except sqlite3.OperationalError:
            agendas_count = 0
        minutes_count = self.db["minutes"].count
        page_count = agendas_count + minutes_count
        self.message_print(
            f"Processed {page_count} pages, {agendas_count} agendas, {minutes_count} minutes. Formerly {self.previous_page_count} pages processed."
        )

    def do_ocr(self, prefix: str = "") -> None:
        self.images_dir = f"{self.dir_prefix}{prefix}/images"
        pdf_dir = f"{self.dir_prefix}{prefix}/pdfs"
        txt_dir = f"{self.dir_prefix}{prefix}/txt"
        processed_dir = f"{self.dir_prefix}{prefix}/processed"
        if not os.path.exists(processed_dir):
            os.makedirs(processed_dir)
        if not os.path.exists(f"{pdf_dir}"):
            self.message_print(f"No PDFs found in {pdf_dir}")
            return
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

        with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
            future_to_job = {executor.submit(self.do_ocr_job, job): job for job in jobs}

            for future in concurrent.futures.as_completed(future_to_job):
                job = future_to_job[future]
                try:
                    data = future.result()
                except Exception as exc:
                    self.message_print(f"{job!r} generated an exception: {exc}")
                else:
                    if data is not None:
                        self.message_print(f"{job!r} page is {len(data)} bytes")

    def do_ocr_job(self, job: tuple[str, str, str]) -> None:
        if not PDF_SUPPORT:
            raise ImportError(
                "PDF support requires optional dependencies. Install with: pip install clerk[pdf]"
            )
        st = time.time()
        prefix = job[0]
        meeting = job[1]
        date = job[2]

        self.message_print(f"Processing {job}")
        doc_path = f"{self.dir_prefix}{prefix}/pdfs/{meeting}/{date}.pdf"
        doc_image_dir_path = f"{self.dir_prefix}{prefix}/images/{meeting}/{date}"
        try:
            with tempfile.TemporaryDirectory() as path:
                doc = convert_from_path(
                    doc_path, fmt="png", size=(1276, 1648), dpi=150, output_folder=path
                )
                for number, page in enumerate(doc):
                    page_number = number + 1
                    page_image_path = f"{doc_image_dir_path}/{page_number}.png"
                    if os.path.exists(page_image_path) and not prefix:
                        continue
                    page.save(page_image_path, "PNG")
        except Exception as e:
            self.message_print(f"{doc_path} failed to process: {e}")
            return
        for page_image in os.listdir(f"{doc_image_dir_path}"):
            page_image_path = f"{doc_image_dir_path}/{page_image}"
            remote_storage_path = f"/{self.subdomain}{prefix}/{meeting}/{date}/{page_image}"
            txt_filename = page_image.replace(".png", ".txt")
            txt_filepath = f"{self.dir_prefix}{prefix}/txt/{meeting}/{date}/{txt_filename}"
            if not os.path.exists(txt_filepath):
                try:
                    text = subprocess.check_output(
                        [
                            "tesseract",
                            "-l",
                            self.ocr_lang,
                            "--dpi",
                            "150",
                            "--oem",
                            "1",
                            page_image_path,
                            "stdout",
                        ],
                        stderr=subprocess.DEVNULL,
                    )

                    with open(
                        txt_filepath,
                        "wb",
                    ) as textfile:
                        textfile.write(text)
                except Exception as e:
                    self.message_print(f"error processing {page_image_path}, {e}")
                pm.hook.upload_static_file(
                    file_path=page_image_path, storage_path=remote_storage_path
                )
            if page_image.endswith(".txt"):
                continue
        processed_path = f"{self.dir_prefix}{prefix}/processed/{meeting}/{date}.txt"
        with open(processed_path, "a"):
            os.utime(processed_path, None)
        remote_pdf_path = f"{self.subdomain}{prefix}/_pdfs/{meeting}/{date}.pdf"
        pm.hook.upload_static_file(file_path=doc_path, storage_path=remote_pdf_path)
        os.remove(doc_path)
        shutil.rmtree(doc_image_dir_path)
        et = time.time()
        elapsed_time = et - st
        self.message_print(f"{page_image_path} OCR time: {elapsed_time} seconds")

    def fetch_events(self) -> None:
        """Subclasses must override this to fetch meeting data."""
        raise NotImplementedError("Subclasses must implement fetch_events()")
