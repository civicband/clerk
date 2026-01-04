#!/usr/bin/env python
"""Test that utils.py imports correctly with new dataclasses."""

try:
    from src.clerk.utils import MeetingDateGroup, PageData, PageFile
    print("SUCCESS: All dataclasses imported correctly")
    print(f"PageFile: {PageFile}")
    print(f"MeetingDateGroup: {MeetingDateGroup}")
    print(f"PageData: {PageData}")

    # Test instantiation
    pf = PageFile(meeting="test", date="2024-01-01", page_num=1, text="text", page_image_path="/path")
    print(f"PageFile instance: {pf}")

    mdg = MeetingDateGroup(meeting="test", date="2024-01-01", page_indices=[1, 2, 3])
    print(f"MeetingDateGroup instance: {mdg}")

    pd = PageData(page_id="id1", text="text", page_file_path="/path", content_hash="hash", cached_extraction=None)
    print(f"PageData instance: {pd}")

except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
