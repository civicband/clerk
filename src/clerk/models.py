"""SQLAlchemy table definitions for civic.db schema."""

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table

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
    Column("status", String),
    Column("last_updated", String),
    Column("last_deployed", String),
    Column("lat", String),
    Column("lng", String),
    Column("extraction_status", String, server_default="pending"),
    Column("last_extracted", String),
)

job_tracking_table = Table(
    "job_tracking",
    metadata,
    Column("rq_job_id", String, primary_key=True),
    Column("site_id", String, nullable=False, index=True),
    Column("job_type", String, nullable=False),
    Column("stage", String),
    Column("created_at", DateTime),
)

site_progress_table = Table(
    "site_progress",
    metadata,
    Column("site_id", String, primary_key=True),
    Column("current_stage", String),
    Column("stage_total", Integer, server_default="0"),
    Column("stage_completed", Integer, server_default="0"),
    Column("started_at", DateTime),
    Column("updated_at", DateTime),
)
