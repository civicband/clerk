"""Tests for refactored utility functions."""
import pytest
import sqlite_utils
from clerk.utils import PageFile, MeetingDateGroup, group_pages_by_meeting_date, create_meetings_schema, collect_page_files


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
