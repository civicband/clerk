"""Sample workflow demonstrating end-to-end usage of Clerk.

This example shows how to use Clerk programmatically rather than via CLI.
"""

import os
import sqlite_utils
from pathlib import Path


def setup_environment():
    """Set up environment for standalone development."""
    # Use a temporary directory for testing
    import tempfile

    storage_dir = tempfile.mkdtemp(prefix="clerk_demo_")
    os.environ["STORAGE_DIR"] = storage_dir

    print(f"Using storage directory: {storage_dir}")
    return storage_dir


def create_site():
    """Create a new site programmatically."""
    from clerk.utils import assert_db_exists

    print("\n=== Creating Site ===")

    # Ensure civic.db exists
    db = assert_db_exists()

    # Insert a new site
    site_data = {
        "subdomain": "demo.civic.band",
        "name": "Demo City Council",
        "state": "CA",
        "country": "US",
        "kind": "city-council",
        "scraper": "test_scraper",
        "pages": 0,
        "start_year": 2024,
        "extra": None,
        "status": "new",
        "last_updated": "2024-01-01T00:00:00",
        "lat": "37.7749",
        "lng": "-122.4194",
    }

    db["sites"].insert(site_data, pk="subdomain", replace=True)
    print(f"Created site: {site_data['subdomain']}")

    return site_data


def prepare_sample_data(storage_dir, subdomain):
    """Create sample text files for testing."""
    print("\n=== Preparing Sample Data ===")

    # Create directory structure
    base_dir = Path(storage_dir) / subdomain
    minutes_dir = base_dir / "txt" / "City Council" / "2024-01-15"
    minutes_dir.mkdir(parents=True, exist_ok=True)

    # Create sample text files
    (minutes_dir / "1.txt").write_text(
        """DEMO CITY COUNCIL
Regular Meeting - January 15, 2024
Page 1

CALL TO ORDER
Mayor Smith called the meeting to order at 7:00 PM.

ROLL CALL
Present: Mayor Smith, Councilmember Jones, Councilmember Davis
Absent: Councilmember Williams
"""
    )

    (minutes_dir / "2.txt").write_text(
        """DEMO CITY COUNCIL
Regular Meeting - January 15, 2024
Page 2

PUBLIC COMMENT
John Doe addressed the council regarding park improvements.
Jane Smith spoke about library funding.

CONSENT CALENDAR
Motion to approve the consent calendar passed unanimously.
"""
    )

    print(f"Created sample data in {minutes_dir}")


def build_database(subdomain):
    """Build database from text files."""
    print("\n=== Building Database ===")

    from clerk.cli import build_db_from_text_internal

    # Get storage path
    storage_dir = os.environ.get("STORAGE_DIR", "../sites")
    db_path = Path(storage_dir) / subdomain / "meetings.db"

    # Create initial database so backup doesn't fail
    db = sqlite_utils.Database(db_path)
    db["temp"].insert({"id": 1})

    # Build the database
    build_db_from_text_internal(subdomain)

    # Verify the database
    db = sqlite_utils.Database(db_path)
    print(f"Database created: {db_path}")
    print(f"  - Tables: {', '.join(db.table_names())}")
    print(f"  - Minutes count: {db['minutes'].count}")


def enable_search(subdomain):
    """Enable full-text search on the database."""
    print("\n=== Enabling Full-Text Search ===")

    from clerk.cli import rebuild_site_fts_internal

    rebuild_site_fts_internal(subdomain)
    print("FTS indexes created")


def search_database(subdomain):
    """Perform a search on the database."""
    print("\n=== Searching Database ===")

    storage_dir = os.environ.get("STORAGE_DIR", "../sites")
    db_path = Path(storage_dir) / subdomain / "meetings.db"

    db = sqlite_utils.Database(db_path)

    # Search for "library"
    query = "SELECT * FROM minutes WHERE text MATCH 'library'"
    results = list(db.execute(query).fetchall())

    print(f"Search for 'library': {len(results)} results")
    if results:
        print(f"  - Found in: {results[0][1]}")  # meeting name


def update_page_count(subdomain):
    """Update the page count for a site."""
    print("\n=== Updating Page Count ===")

    from clerk.cli import update_page_count

    update_page_count(subdomain)

    # Verify update
    from clerk.utils import assert_db_exists

    db = assert_db_exists()
    site = db["sites"].get(subdomain)
    print(f"Page count updated: {site['pages']} pages")


def use_plugin_system():
    """Demonstrate using the plugin system."""
    print("\n=== Using Plugin System ===")

    from clerk.utils import pm
    from examples.basic_plugin import BasicPlugin

    # Register a plugin
    plugin = BasicPlugin()
    pm.register(plugin)

    print(f"Registered plugin: {plugin.__class__.__name__}")
    print(f"Total plugins: {len(pm.get_plugins())}")

    # Call a hook
    result = pm.hook.fetcher_class(label="basic_scraper")
    print(f"fetcher_class hook result: {result}")


def complete_workflow():
    """Run the complete workflow."""
    print("=== Clerk Sample Workflow ===\n")

    # Setup
    storage_dir = setup_environment()

    # Create site
    site = create_site()
    subdomain = site["subdomain"]

    # Prepare data
    prepare_sample_data(storage_dir, subdomain)

    # Build database
    build_database(subdomain)

    # Enable search
    enable_search(subdomain)

    # Search
    search_database(subdomain)

    # Update metadata
    update_page_count(subdomain)

    # Demonstrate plugins
    use_plugin_system()

    print("\n=== Workflow Complete ===")
    print(f"Storage directory: {storage_dir}")
    print(f"You can explore the generated files at: {Path(storage_dir) / subdomain}")

    return storage_dir


if __name__ == "__main__":
    # Run the complete workflow
    storage_dir = complete_workflow()

    # Cleanup option
    print("\nTo clean up temporary files:")
    print(f"  rm -rf {storage_dir}")
