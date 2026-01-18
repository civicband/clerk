"""SQLAlchemy table definitions for civic.db schema."""

from sqlalchemy import Boolean, Column, DateTime, Integer, MetaData, String, Table, Text
from sqlalchemy.sql import func

metadata = MetaData()

sites_table = Table(
    "sites",
    metadata,
    Column("subdomain", String, primary_key=True, nullable=False),
    Column("name", String),
    Column("state", String),
    Column("kind", String),
    Column("scraper", String),
    Column("pages", Integer),
    Column("start_year", Integer),
    Column("extra", String),
    Column("country", String),
    Column("lat", String),
    Column("lng", String),

    # Pipeline state
    Column("current_stage", String),
    Column("started_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),

    # Fetch counters
    Column("fetch_total", Integer, server_default="0"),
    Column("fetch_completed", Integer, server_default="0"),
    Column("fetch_failed", Integer, server_default="0"),

    # OCR counters
    Column("ocr_total", Integer, server_default="0"),
    Column("ocr_completed", Integer, server_default="0"),
    Column("ocr_failed", Integer, server_default="0"),

    # Compilation counters
    Column("compilation_total", Integer, server_default="0"),
    Column("compilation_completed", Integer, server_default="0"),
    Column("compilation_failed", Integer, server_default="0"),

    # Extraction counters
    Column("extraction_total", Integer, server_default="0"),
    Column("extraction_completed", Integer, server_default="0"),
    Column("extraction_failed", Integer, server_default="0"),

    # Deploy counters
    Column("deploy_total", Integer, server_default="0"),
    Column("deploy_completed", Integer, server_default="0"),
    Column("deploy_failed", Integer, server_default="0"),

    # Coordinator tracking
    Column("coordinator_enqueued", Boolean, server_default="FALSE"),

    # Error tracking
    Column("last_error_stage", String),
    Column("last_error_message", Text),
    Column("last_error_at", DateTime(timezone=True)),

    # Deprecated (keep during migration)
    Column("status", String),
    Column("extraction_status", String, server_default="pending"),
    Column("last_updated", String),
    Column("last_deployed", String),
    Column("last_extracted", String),
)

job_tracking_table = Table(
    "job_tracking",
    metadata,
    Column("rq_job_id", String, primary_key=True),
    Column("subdomain", String, nullable=False, index=True),
    Column("job_type", String, nullable=False),
    Column("stage", String, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

site_progress_table = Table(
    "site_progress",
    metadata,
    Column("subdomain", String, primary_key=True),
    Column("current_stage", String, nullable=True),
    Column("stage_total", Integer, server_default="0"),
    Column("stage_completed", Integer, server_default="0"),
    Column("started_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)
