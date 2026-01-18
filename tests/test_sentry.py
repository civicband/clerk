"""Tests for Sentry integration and error fingerprinting."""

from clerk.sentry import before_send


class TestBeforeSend:
    """Test the before_send hook for Sentry event fingerprinting."""

    def test_pdf_file_not_found_log_message(self):
        """PDF file not found log messages should be grouped together."""
        event1 = {"logentry": {"message": "PDF file not found: /path/to/site1/pdfs/file.pdf"}}
        event2 = {
            "logentry": {"message": "PDF file not found: /different/path/site2/pdfs/other.pdf"}
        }

        result1 = before_send(event1, {})
        result2 = before_send(event2, {})

        assert result1["fingerprint"] == ["pdf-file-not-found"]
        assert result2["fingerprint"] == ["pdf-file-not-found"]

    def test_no_text_files_found_exception(self):
        """No text files found exceptions should be grouped together."""
        event1 = {"exception": {"values": [{"value": "No text files found in /path/to/site1/txt"}]}}
        event2 = {
            "exception": {"values": [{"value": "No text files found in /different/path/site2/txt"}]}
        }

        result1 = before_send(event1, {})
        result2 = before_send(event2, {})

        assert result1["fingerprint"] == ["no-text-files-found"]
        assert result2["fingerprint"] == ["no-text-files-found"]

    def test_error_fetching_year(self):
        """Error fetching year messages should be grouped together."""
        event1 = {"exception": {"values": [{"value": "Error fetching year 2026 for Committee A"}]}}
        event2 = {"exception": {"values": [{"value": "Error fetching year 2025 for Committee B"}]}}

        result1 = before_send(event1, {})
        result2 = before_send(event2, {})

        assert result1["fingerprint"] == ["error-fetching-year"]
        assert result2["fingerprint"] == ["error-fetching-year"]

    def test_error_fetching_https_grouped_by_domain(self):
        """Error fetching URL messages should be grouped by domain."""
        event1 = {
            "exception": {"values": [{"value": "Error fetching https://example.com/page1/path"}]}
        }
        event2 = {
            "exception": {
                "values": [{"value": "Error fetching https://example.com/page2/different"}]
            }
        }
        event3 = {"exception": {"values": [{"value": "Error fetching https://other.com/page"}]}}

        result1 = before_send(event1, {})
        result2 = before_send(event2, {})
        result3 = before_send(event3, {})

        assert result1["fingerprint"] == ["fetch-error", "example.com"]
        assert result2["fingerprint"] == ["fetch-error", "example.com"]
        assert result3["fingerprint"] == ["fetch-error", "other.com"]

    def test_ocr_coordinator_failed(self):
        """OCR coordinator failures should be grouped together."""
        event = {
            "exception": {"values": [{"value": "ocr_coordinator_failed: No text files found"}]}
        }

        result = before_send(event, {})

        assert result["fingerprint"] == ["ocr-coordinator-failed"]

    def test_empty_pdf_file_log_message(self):
        """Empty PDF file log messages should be grouped together."""
        event1 = {"logentry": {"message": "Skipping empty PDF file /path/to/site1/pdfs/empty.pdf"}}
        event2 = {
            "logentry": {"message": "Skipping empty PDF file /path/to/site2/pdfs/another.pdf"}
        }

        result1 = before_send(event1, {})
        result2 = before_send(event2, {})

        assert result1["fingerprint"] == ["empty-pdf-file"]
        assert result2["fingerprint"] == ["empty-pdf-file"]

    def test_file_not_found_error_pdf(self):
        """FileNotFoundError for PDF files should be grouped together."""
        event1 = {
            "exception": {
                "values": [
                    {
                        "type": "FileNotFoundError",
                        "value": "/path/to/site1/pdfs/missing.pdf",
                    }
                ]
            }
        }
        event2 = {
            "exception": {
                "values": [
                    {
                        "type": "FileNotFoundError",
                        "value": "/different/path/site2/pdfs/notfound.pdf",
                    }
                ]
            }
        }

        result1 = before_send(event1, {})
        result2 = before_send(event2, {})

        assert result1["fingerprint"] == ["file-not-found", "pdf"]
        assert result2["fingerprint"] == ["file-not-found", "pdf"]

    def test_file_not_found_error_txt(self):
        """FileNotFoundError for txt files should be grouped together."""
        event = {
            "exception": {
                "values": [
                    {
                        "type": "FileNotFoundError",
                        "value": "/path/to/site/txt/missing.txt",
                    }
                ]
            }
        }

        result = before_send(event, {})

        assert result["fingerprint"] == ["file-not-found", "txt"]

    def test_file_not_found_error_other(self):
        """FileNotFoundError for other files should be grouped separately."""
        event = {
            "exception": {
                "values": [{"type": "FileNotFoundError", "value": "/path/to/config.json"}]
            }
        }

        result = before_send(event, {})

        assert result["fingerprint"] == ["file-not-found", "other"]

    def test_log_message_via_message_field(self):
        """Log messages can also come through the message field."""
        event = {"message": "PDF file not found: /some/path/file.pdf"}

        result = before_send(event, {})

        assert result["fingerprint"] == ["pdf-file-not-found"]

    def test_no_message_returns_event_unchanged(self):
        """Events without messages should be returned unchanged."""
        event = {"some": "data"}

        result = before_send(event, {})

        assert result == event
        assert "fingerprint" not in result

    def test_unmatched_message_returns_event_unchanged(self):
        """Messages that don't match patterns should be returned unchanged."""
        event = {"exception": {"values": [{"value": "Some random error message"}]}}

        result = before_send(event, {})

        assert result == event
        assert "fingerprint" not in result

    def test_pattern_priority_first_match_wins(self):
        """When multiple patterns could match, the first one wins."""
        # This message could match both "No text files found" and has a path
        # But "No text files found" pattern comes first in the code
        event = {"exception": {"values": [{"value": "No text files found in /path/to/pdfs/site"}]}}

        result = before_send(event, {})

        assert result["fingerprint"] == ["no-text-files-found"]
