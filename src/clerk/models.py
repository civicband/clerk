"""SQLAlchemy table definitions for civic.db schema."""

from sqlalchemy import Column, Integer, MetaData, String, Table

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
