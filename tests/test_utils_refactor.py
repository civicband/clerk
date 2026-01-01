"""Tests for refactored utility functions."""

import json

import pytest
import sqlite_utils

from clerk.extraction import EXTRACTION_ENABLED, create_meeting_context
from clerk.utils import (
    PageFile,
    batch_parse_with_spacy,
    collect_page_data_with_cache,
    collect_page_files,
    create_meetings_schema,
    group_pages_by_meeting_date,
    load_pages_from_db,
    process_page_for_db,
)


def test_group_pages_by_meeting_date_single_meeting():
    """Test grouping pages from a single meeting date."""
    pages = [
        PageFile("council", "2024-01-15", 1, "text1", "/council/2024-01-15/0001.png"),
        PageFile("council", "2024-01-15", 2, "text2", "/council/2024-01-15/0002.png"),
    ]

    groups = group_pages_by_meeting_date(pages)

    assert len(groups) == 1
    assert groups[0].meeting == "council"
    assert groups[0].date == "2024-01-15"
    assert groups[0].page_indices == [0, 1]


def test_group_pages_by_meeting_date_multiple_dates():
    """Test grouping pages from multiple meeting dates."""
    pages = [
        PageFile("council", "2024-01-15", 1, "text1", "/path1.png"),
        PageFile("council", "2024-01-15", 2, "text2", "/path2.png"),
        PageFile("council", "2024-02-20", 1, "text3", "/path3.png"),
        PageFile("planning", "2024-01-15", 1, "text4", "/path4.png"),
    ]

    groups = group_pages_by_meeting_date(pages)

    assert len(groups) == 3
    assert groups[0].meeting == "council"
    assert groups[0].date == "2024-01-15"
    assert groups[0].page_indices == [0, 1]
    assert groups[1].meeting == "council"
    assert groups[1].date == "2024-02-20"
    assert groups[1].page_indices == [2]
    assert groups[2].meeting == "planning"
    assert groups[2].date == "2024-01-15"
    assert groups[2].page_indices == [3]


def test_group_pages_by_meeting_date_empty():
    """Test grouping with no pages."""
    groups = group_pages_by_meeting_date([])
    assert groups == []


def test_create_meetings_schema():
    """Test schema creation for meetings database."""
    db = sqlite_utils.Database(memory=True)

    create_meetings_schema(db)

    assert "minutes" in db.table_names()
    assert "agendas" in db.table_names()

    # Check schema
    minutes_cols = {col.name: col.type for col in db["minutes"].columns}
    assert minutes_cols["id"] == "TEXT"
    assert minutes_cols["meeting"] == "TEXT"
    assert minutes_cols["date"] == "TEXT"
    assert minutes_cols["page"] == "INTEGER"
    assert minutes_cols["text"] == "TEXT"
    assert minutes_cols["page_image"] == "TEXT"
    assert minutes_cols["entities_json"] == "TEXT"
    assert minutes_cols["votes_json"] == "TEXT"

    # Check primary key
    assert db["minutes"].pks == ["id"]
    assert db["agendas"].pks == ["id"]


def test_collect_page_files(tmp_path):
    """Test collecting page files from directory structure."""
    # Create fixture directory structure: txt_dir/meeting/date/page.txt
    txt_dir = tmp_path / "txt"
    meeting_dir = txt_dir / "council"
    date_dir = meeting_dir / "2024-01-15"
    date_dir.mkdir(parents=True)

    # Create page files
    (date_dir / "0001.txt").write_text("Page 1 content")
    (date_dir / "0002.txt").write_text("Page 2 content")

    # Second date
    date_dir2 = meeting_dir / "2024-02-20"
    date_dir2.mkdir(parents=True)
    (date_dir2 / "0001.txt").write_text("Page 3 content")

    page_files = collect_page_files(str(txt_dir))

    assert len(page_files) == 3
    assert page_files[0].meeting == "council"
    assert page_files[0].date == "2024-01-15"
    assert page_files[0].page_num == 1
    assert page_files[0].text == "Page 1 content"
    assert page_files[0].page_image_path == "/council/2024-01-15/0001.png"

    assert page_files[2].date == "2024-02-20"
    assert page_files[2].page_num == 1


def test_collect_page_files_empty(tmp_path):
    """Test with empty directory."""
    txt_dir = tmp_path / "empty"
    txt_dir.mkdir()

    page_files = collect_page_files(str(txt_dir))

    assert page_files == []


@pytest.mark.skipif(not EXTRACTION_ENABLED, reason="Extraction not enabled")
def test_batch_parse_with_spacy():
    """Test batch parsing with spaCy."""
    from clerk.extraction import get_nlp

    # Skip if spaCy model not available
    if get_nlp() is None:
        pytest.skip("spaCy model not installed")

    texts = ["This is a test.", "Another test sentence."]

    docs = batch_parse_with_spacy(texts, "test.civic.band")

    assert len(docs) == 2
    assert docs[0] is not None
    assert len(list(docs[0])) > 0  # Has tokens


def test_batch_parse_with_spacy_extraction_disabled():
    """Test batch parsing when extraction is disabled."""
    import os

    old_val = os.environ.get("ENABLE_EXTRACTION")
    os.environ["ENABLE_EXTRACTION"] = "0"

    try:
        texts = ["Test"]
        docs = batch_parse_with_spacy(texts, "test.civic.band")
        assert all(doc is None for doc in docs)
    finally:
        if old_val:
            os.environ["ENABLE_EXTRACTION"] = old_val
        else:
            os.environ.pop("ENABLE_EXTRACTION", None)


def test_batch_parse_with_spacy_empty():
    """Test with empty text list."""
    docs = batch_parse_with_spacy([], "test.civic.band")
    assert docs == []


def test_process_page_for_db():
    """Test processing a page for database insertion."""
    page_file = PageFile(
        meeting="council",
        date="2024-01-15",
        page_num=1,
        text="Mayor Smith called the meeting to order. Motion to approve passed 5-0.",
        page_image_path="/council/2024-01-15/0001.png",
    )

    context = create_meeting_context()

    # Process without doc (extraction disabled case)
    entry = process_page_for_db(
        page_file=page_file,
        doc=None,
        context=context,
        subdomain="test.civic.band",
        table_name="minutes",
        municipality=None,
    )

    assert entry["meeting"] == "council"
    assert entry["date"] == "2024-01-15"
    assert entry["page"] == 1
    assert entry["text"] == page_file.text
    assert entry["page_image"] == "/council/2024-01-15/0001.png"
    assert "id" in entry
    assert len(entry["id"]) == 12  # Hash prefix

    # Check entities/votes JSON (should be empty when extraction disabled)
    entities = json.loads(entry["entities_json"])
    votes = json.loads(entry["votes_json"])
    assert "persons" in entities
    assert "votes" in votes


def test_load_pages_from_db(tmp_path):
    """Test loading pages from database."""
    # Create test database
    db_path = tmp_path / "test.db"
    db = sqlite_utils.Database(str(db_path))
    create_meetings_schema(db)

    # Insert test data
    db["minutes"].insert_all(
        [
            {
                "id": "abc",
                "meeting": "council",
                "date": "2024-01-15",
                "page": 1,
                "text": "test",
                "page_image": "/path.png",
                "entities_json": "{}",
                "votes_json": "{}",
            },
            {
                "id": "def",
                "meeting": "council",
                "date": "2024-01-15",
                "page": 2,
                "text": "test2",
                "page_image": "/path2.png",
                "entities_json": "{}",
                "votes_json": "{}",
            },
        ]
    )
    db.close()

    # Create subdomain directory structure
    subdomain_dir = tmp_path / "test.civic.band"
    subdomain_dir.mkdir()
    (subdomain_dir / "meetings.db").write_bytes((tmp_path / "test.db").read_bytes())

    # Test loading (need to set STORAGE_DIR)
    import os

    old_storage = os.environ.get("STORAGE_DIR")
    os.environ["STORAGE_DIR"] = str(tmp_path)

    try:
        pages = load_pages_from_db("test.civic.band", "minutes")

        assert len(pages) == 2
        assert pages[0]["id"] == "abc"
        assert pages[0]["meeting"] == "council"
        assert pages[1]["page"] == 2
    finally:
        if old_storage:
            os.environ["STORAGE_DIR"] = old_storage
        else:
            os.environ.pop("STORAGE_DIR", None)


def test_collect_page_data_with_cache(tmp_path):
    """Test collecting page data with cache checking."""
    from clerk.utils import hash_text_content

    # Create text files
    txt_dir = tmp_path / "txt"
    meeting_dir = txt_dir / "council" / "2024-01-15"
    meeting_dir.mkdir(parents=True)

    page1 = meeting_dir / "0001.txt"
    test_content = "Test content"
    page1.write_text(test_content)

    # Create cache file with correct hash
    cache_file = meeting_dir / "0001.txt.extracted.json"
    cache_data = {
        "content_hash": hash_text_content(test_content),
        "extracted_at": "2024-01-01T00:00:00",
        "entities": {"persons": [], "orgs": [], "locations": []},
        "votes": {"votes": []},
    }
    cache_file.write_text(json.dumps(cache_data))

    pages = [{"id": "test1", "meeting": "council", "date": "2024-01-15", "page": 1}]

    # Mock STORAGE_DIR
    import os

    old_storage = os.environ.get("STORAGE_DIR")
    os.environ["STORAGE_DIR"] = str(tmp_path)
    subdomain_dir = tmp_path / "test.civic.band"
    subdomain_dir.mkdir()
    txt_final = subdomain_dir / "txt"
    txt_final.symlink_to(txt_dir)

    try:
        page_data = collect_page_data_with_cache(
            pages, "test.civic.band", "minutes", force_extraction=False
        )

        assert len(page_data) == 1
        assert page_data[0].page_id == "test1"
        assert page_data[0].text == "Test content"
        assert page_data[0].cached_extraction is not None
    finally:
        if old_storage:
            os.environ["STORAGE_DIR"] = old_storage
        else:
            os.environ.pop("STORAGE_DIR", None)
