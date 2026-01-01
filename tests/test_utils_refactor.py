"""Tests for refactored utility functions."""
import pytest
from clerk.utils import PageFile, MeetingDateGroup, group_pages_by_meeting_date


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
