"""Sentry integration for error tracking and monitoring.

Initializes Sentry SDK if SENTRY_DSN environment variable is set.
"""

import os

import sentry_sdk


def init_sentry():
    """Initialize Sentry SDK if SENTRY_DSN is configured.

    Environment variables:
        SENTRY_DSN: Sentry Data Source Name (DSN) URL
        SENTRY_ENVIRONMENT: Environment name (default: production)
        SENTRY_TRACES_SAMPLE_RATE: Traces sample rate (default: 0.0)

    Examples:
        export SENTRY_DSN="https://key@host/project"
        export SENTRY_ENVIRONMENT="production"
        export SENTRY_TRACES_SAMPLE_RATE="0.1"
    """
    sentry_dsn = os.getenv("SENTRY_DSN")

    if not sentry_dsn:
        # Sentry not configured, skip initialization
        return

    environment = os.getenv("SENTRY_ENVIRONMENT", "production")
    traces_sample_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0"))

    sentry_sdk.init(
        dsn=sentry_dsn,
        environment=environment,
        send_default_pii=True,
        max_request_body_size="always",
        traces_sample_rate=traces_sample_rate,
        # Capture exception info for RQ jobs
        integrations=[],
    )
