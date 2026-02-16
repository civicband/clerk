"""Centralized settings management for Clerk.

This module provides a centralized way to access environment variables,
automatically loading from .env files first before falling back to system
environment variables.

Usage:
    from clerk.settings import get_env, Settings

    # Get a single environment variable
    database_url = get_env("DATABASE_URL")
    redis_url = get_env("REDIS_URL", default="redis://localhost:6379")

    # Or use the Settings object for commonly-used settings
    settings = Settings()
    database_url = settings.DATABASE_URL
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env file from current working directory on module import
# This respects where the user invoked Python from
_dotenv_path = Path.cwd() / ".env"
if _dotenv_path.exists():
    load_dotenv(_dotenv_path)


def get_env(key: str, default: str | None = None) -> str | None:
    """Get environment variable value, loading from .env first.

    The .env file is automatically loaded when this module is imported,
    so this function will return values from .env files with higher
    priority than system environment variables.

    Args:
        key: Environment variable name
        default: Default value if key is not found

    Returns:
        Environment variable value or default

    Examples:
        >>> database_url = get_env("DATABASE_URL")
        >>> redis_url = get_env("REDIS_URL", "redis://localhost:6379")
    """
    return os.getenv(key, default)


def get_env_bool(key: str, default: bool = False) -> bool:
    """Get environment variable as boolean.

    Interprets the following as True (case-insensitive):
    - "true", "yes", "1", "on"

    All other values are False.

    Args:
        key: Environment variable name
        default: Default value if key is not found

    Returns:
        Boolean value

    Examples:
        >>> debug = get_env_bool("DEBUG", False)
    """
    value = get_env(key)
    if value is None:
        return default
    return value.lower() in ("true", "yes", "1", "on")


def get_env_int(key: str, default: int | None = None) -> int | None:
    """Get environment variable as integer.

    Args:
        key: Environment variable name
        default: Default value if key is not found or cannot be parsed

    Returns:
        Integer value or default

    Examples:
        >>> port = get_env_int("PORT", 8000)
    """
    value = get_env(key)
    if value is None:
        return default

    try:
        return int(value)
    except ValueError:
        return default


def get_env_float(key: str, default: float | None = None) -> float | None:
    """Get environment variable as float.

    Args:
        key: Environment variable name
        default: Default value if key is not found or cannot be parsed

    Returns:
        Float value or default

    Examples:
        >>> rate = get_env_float("SENTRY_TRACES_SAMPLE_RATE", 0.0)
    """
    value = get_env(key)
    if value is None:
        return default

    try:
        return float(value)
    except ValueError:
        return default


class Settings:
    """Centralized settings object for commonly-used environment variables.

    Provides convenient access to environment variables with type safety
    and default values.

    Usage:
        settings = Settings()
        database_url = settings.DATABASE_URL
        redis_url = settings.REDIS_URL
    """

    def __init__(self) -> None:
        """Initialize settings from environment variables."""
        # Database Configuration
        self.DATABASE_URL: str | None = get_env("DATABASE_URL")

        # Redis Configuration
        self.REDIS_URL: str = get_env("REDIS_URL", "redis://localhost:6379")

        # Storage Configuration
        self.STORAGE_DIR: str = get_env("STORAGE_DIR", "../sites")

        # OCR Configuration
        self.DEFAULT_OCR_BACKEND: str = get_env("DEFAULT_OCR_BACKEND", "tesseract")
        self.OCR_JOB_TIMEOUT: str = get_env("OCR_JOB_TIMEOUT", "20m")

        # Worker Configuration
        self.FETCH_WORKERS: int = get_env_int("FETCH_WORKERS", 2) or 2
        self.OCR_WORKERS: int = get_env_int("OCR_WORKERS", 4) or 4
        self.COMPILATION_WORKERS: int = get_env_int("COMPILATION_WORKERS", 2) or 2
        self.EXTRACTION_WORKERS: int = get_env_int("EXTRACTION_WORKERS", 0) or 0
        self.DEPLOY_WORKERS: int = get_env_int("DEPLOY_WORKERS", 1) or 1

        # Logging Configuration
        self.LOKI_URL: str | None = get_env("LOKI_URL")

        # Sentry Configuration
        self.SENTRY_DSN: str | None = get_env("SENTRY_DSN")
        self.SENTRY_ENVIRONMENT: str = get_env("SENTRY_ENVIRONMENT", "production")
        self.SENTRY_TRACES_SAMPLE_RATE: float = (
            get_env_float("SENTRY_TRACES_SAMPLE_RATE", 0.0) or 0.0
        )

        # Testing Configuration
        self.DYLD_FALLBACK_LIBRARY_PATH: str | None = get_env("DYLD_FALLBACK_LIBRARY_PATH")

    def __repr__(self) -> str:
        """Return string representation of settings."""
        # Mask sensitive values
        safe_attrs = {}
        for key, value in self.__dict__.items():
            if any(
                sensitive in key.upper()
                for sensitive in ["DSN", "URL", "PASSWORD", "SECRET", "TOKEN", "KEY"]
            ):
                if value:
                    safe_attrs[key] = "***"
                else:
                    safe_attrs[key] = None
            else:
                safe_attrs[key] = value

        return f"Settings({safe_attrs})"


# Create a singleton instance for convenient import
settings = Settings()
