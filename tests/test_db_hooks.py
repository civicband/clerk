"""Tests for database plugin hooks."""

import sqlite_utils
from clerk.hookspecs import ClerkSpec


def test_update_site_hookspec_exists():
    """Test that update_site hookspec is defined."""
    assert hasattr(ClerkSpec, "update_site")


def test_create_site_hookspec_exists():
    """Test that create_site hookspec is defined."""
    assert hasattr(ClerkSpec, "create_site")
