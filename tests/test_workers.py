def test_fetch_site_job_exists():
    """Test that fetch_site_job function exists."""
    from clerk.workers import fetch_site_job

    assert callable(fetch_site_job)


def test_ocr_page_job_exists():
    """Test that ocr_page_job function exists."""
    from clerk.workers import ocr_page_job

    assert callable(ocr_page_job)
