"""Tests for clerk.output module."""

import json
import logging

from clerk import output
from clerk.cli import JsonFormatter


class TestLog:
    """Tests for the log() function."""

    def setup_method(self):
        """Reset output module state before each test."""
        output._quiet = False
        output._default_subdomain = None

    def test_log_message_only(self, caplog):
        """log() with just a message logs at INFO level."""
        with caplog.at_level(logging.INFO):
            output.log("Test message")

        assert len(caplog.records) == 1
        assert caplog.records[0].message == "Test message"
        assert caplog.records[0].levelname == "INFO"

    def test_log_with_subdomain(self, caplog):
        """log() with subdomain passes it as extra field, not in message."""
        with caplog.at_level(logging.INFO):
            output.log("Test message", subdomain="alameda.ca")

        assert len(caplog.records) == 1
        record = caplog.records[0]
        # Message should NOT contain subdomain
        assert record.message == "Test message"
        assert "subdomain=" not in record.message
        # Subdomain should be in extra field
        assert hasattr(record, "subdomain")
        assert record.subdomain == "alameda.ca"

    def test_log_with_kwargs(self, caplog):
        """log() passes additional kwargs as extra fields."""
        with caplog.at_level(logging.INFO):
            output.log("Fetch complete", subdomain="test.ca", elapsed_time="1.5", pages=10)

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.message == "Fetch complete"
        assert record.subdomain == "test.ca"
        assert record.elapsed_time == "1.5"
        assert record.pages == 10

    def test_log_levels(self, caplog):
        """log() respects the level parameter."""
        with caplog.at_level(logging.DEBUG):
            output.log("Debug message", level="debug")
            output.log("Info message", level="info")
            output.log("Warning message", level="warning")
            output.log("Error message", level="error")

        assert len(caplog.records) == 4
        assert caplog.records[0].levelname == "DEBUG"
        assert caplog.records[1].levelname == "INFO"
        assert caplog.records[2].levelname == "WARNING"
        assert caplog.records[3].levelname == "ERROR"

    def test_log_invalid_level_defaults_to_info(self, caplog):
        """log() with invalid level defaults to INFO."""
        with caplog.at_level(logging.INFO):
            output.log("Test message", level="invalid_level")

        assert len(caplog.records) == 1
        assert caplog.records[0].levelname == "INFO"

    def test_log_includes_run_id_in_extra(self, caplog):
        """Test that run_id is passed to logger.info as extra field."""
        with caplog.at_level(logging.INFO):
            output.log("test message", subdomain="test", run_id="test_123_abc")

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.run_id == "test_123_abc"

    def test_log_includes_stage_in_extra(self, caplog):
        """Test that stage is passed to logger.info as extra field."""
        with caplog.at_level(logging.INFO):
            output.log("test message", subdomain="test", stage="fetch")

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.stage == "fetch"

    def test_log_includes_job_ids_in_extra(self, caplog):
        """Test that job_id and parent_job_id are passed as extra fields."""
        with caplog.at_level(logging.INFO):
            output.log("test message", subdomain="test", job_id="job-123", parent_job_id="job-456")

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.job_id == "job-123"
        assert record.parent_job_id == "job-456"

    def test_log_excludes_none_values(self, caplog):
        """Test that None values are not included in extra dict."""
        with caplog.at_level(logging.INFO):
            output.log("test message", subdomain="test", run_id=None, stage=None)

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert not hasattr(record, 'run_id')
        assert not hasattr(record, 'stage')


class TestConfigure:
    """Tests for the configure() function."""

    def setup_method(self):
        """Reset output module state before each test."""
        output._quiet = False
        output._default_subdomain = None

    def test_configure_quiet(self):
        """configure() sets quiet mode."""
        assert output._quiet is False
        output.configure(quiet=True)
        assert output._quiet is True

    def test_configure_subdomain(self):
        """configure() sets default subdomain."""
        assert output._default_subdomain is None
        output.configure(subdomain="default.ca")
        assert output._default_subdomain == "default.ca"

    def test_configure_both(self):
        """configure() can set both quiet and subdomain."""
        output.configure(quiet=True, subdomain="test.ca")
        assert output._quiet is True
        assert output._default_subdomain == "test.ca"

    def test_log_uses_default_subdomain(self, caplog):
        """log() uses default subdomain when none specified."""
        output.configure(subdomain="default.ca")

        with caplog.at_level(logging.INFO):
            output.log("Test message")

        assert len(caplog.records) == 1
        assert caplog.records[0].subdomain == "default.ca"

    def test_log_overrides_default_subdomain(self, caplog):
        """log() with explicit subdomain overrides default."""
        output.configure(subdomain="default.ca")

        with caplog.at_level(logging.INFO):
            output.log("Test message", subdomain="override.ca")

        assert len(caplog.records) == 1
        assert caplog.records[0].subdomain == "override.ca"


class TestJsonFormatter:
    """Tests for the JsonFormatter class."""

    def test_basic_format(self):
        """JsonFormatter produces valid JSON with required fields."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"
        assert parsed["message"] == "Test message"
        assert "timestamp" in parsed

    def test_includes_extra_fields(self):
        """JsonFormatter includes extra fields in JSON output."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        # Add extra fields as they would be added by extra={}
        record.subdomain = "alameda.ca"
        record.elapsed_time = "1.5"

        result = formatter.format(record)
        parsed = json.loads(result)

        assert parsed["message"] == "Test message"
        assert parsed["subdomain"] == "alameda.ca"
        assert parsed["elapsed_time"] == "1.5"

    def test_excludes_reserved_attrs(self):
        """JsonFormatter excludes standard LogRecord attributes from extra."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        parsed = json.loads(result)

        # These should NOT be in the output (they're reserved)
        assert "lineno" not in parsed
        assert "pathname" not in parsed
        assert "funcName" not in parsed
        assert "msg" not in parsed

    def test_excludes_private_attrs(self):
        """JsonFormatter excludes private attributes (starting with _)."""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record._private_field = "should not appear"

        result = formatter.format(record)
        parsed = json.loads(result)

        assert "_private_field" not in parsed

    def test_includes_exception(self):
        """JsonFormatter includes exception info when present."""
        formatter = JsonFormatter()

        try:
            raise ValueError("Test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
        )

        result = formatter.format(record)
        parsed = json.loads(result)

        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]
        assert "Test error" in parsed["exception"]
