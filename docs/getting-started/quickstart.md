# Quick Start Tutorial

This tutorial walks through creating your first site and running the data pipeline.

## Prerequisites

- Clerk installed (see [Installation](installation.md))
- Basic familiarity with command line

## Step 1: Create a New Site

Create a new civic site:

```bash
clerk new
```

You'll be prompted for:

- **Subdomain**: e.g., `berkeleyca.civic.band`
- **Municipality name**: e.g., `Berkeley`
- **State**: e.g., `CA`
- **Country**: e.g., `USA`
- **Site type**: e.g., `city-council`
- **Scraper type**: Name of your fetcher plugin
- **Start year**: e.g., `2020`
- **Coordinates**: Latitude and longitude

This creates a site entry in the civic.db database and a directory structure at `../sites/berkeleyca.civic.band/`.

## Step 2: Fetch Meeting Data

Update the site to fetch data:

```bash
clerk update --subdomain berkeleyca.civic.band
```

This runs the complete pipeline:
1. Fetches meeting data using the configured scraper
2. Processes PDFs with OCR
3. Extracts text content
4. Stores in local database

### Update Options

```bash
# Fetch all historical data
clerk update --subdomain berkeleyca.civic.band --all-years

# Update next site that needs updating (for cron jobs)
clerk update --next-site
```

## Step 3: Build Database

Build the searchable database from extracted text:

```bash
# Fast build (no entity extraction)
clerk build-db-from-text --subdomain berkeleyca.civic.band

# With entity extraction (slower)
clerk build-db-from-text --subdomain berkeleyca.civic.band --with-extraction
```

This creates `meetings.db` with full-text search enabled.

## Step 4: Extract Entities (Optional)

For entity and vote extraction, run separately:

```bash
clerk extract-entities --subdomain berkeleyca.civic.band
```

This is memory-intensive (~5GB) and runs as a background job.

## Step 5: Build Aggregate Database

Combine all sites into one searchable database:

```bash
clerk build-full-db
```

Creates `../sites/meetings.db` with all sites combined.

## What's Next?

- Learn about [Basic Usage](basic-usage.md) patterns
- Explore the [Plugin System](../developer-guide/plugin-development.md)
- Review [Architecture](../developer-guide/architecture.md)
