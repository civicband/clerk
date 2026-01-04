import httpx
import subprocess
from xml.etree.ElementTree import ParseError

from clerk.ocr_utils import TRANSIENT_ERRORS, PERMANENT_ERRORS, CRITICAL_ERRORS

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
