"""OpenTelemetry setup: traces exported to VictoriaTraces via OTLP/HTTP."""

import atexit
import logging
import os
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.processor.baggage import ALLOW_ALL_BAGGAGE_KEYS, BaggageSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)

DEFAULT_TRACES_ENDPOINT = "http://localhost:10428/insert/opentelemetry/v1/traces"

_configured = False


def build_resource(service_name: str | None = None) -> Resource:
    from clerk import __version__

    return Resource.create(
        {
            "service.name": service_name or os.environ.get("OTEL_SERVICE_NAME", "clerk"),
            "service.version": __version__,
        }
    )


def build_span_exporter(endpoint: str | None = None) -> OTLPSpanExporter:
    url = endpoint or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", DEFAULT_TRACES_ENDPOINT)
    return OTLPSpanExporter(endpoint=url, timeout=5)


def build_provider(endpoint: str | None = None, service_name: str | None = None) -> TracerProvider:
    provider = TracerProvider(resource=build_resource(service_name))
    provider.add_span_processor(BaggageSpanProcessor(ALLOW_ALL_BAGGAGE_KEYS))
    provider.add_span_processor(BatchSpanProcessor(build_span_exporter(endpoint)))
    return provider


def setup_telemetry(endpoint: str | None = None, service_name: str | None = None) -> Any:
    """Configure the global TracerProvider + instrumentations. Idempotent.

    Non-fatal on failure: workers must run even if VictoriaTraces is unreachable
    (BatchSpanProcessor drops spans it cannot export).
    """
    global _configured
    if _configured:
        return trace.get_tracer_provider()
    try:
        trace.set_tracer_provider(build_provider(endpoint, service_name))
    except Exception:
        logger.exception("Telemetry provider setup failed; continuing without tracing")
        return trace.get_tracer_provider()

    try:
        for name, instrumentor in _instrumentors():
            try:
                instrumentor.instrument()
            except Exception:
                logger.warning("Failed to instrument %s; continuing without it", name)
    except Exception:
        logger.warning("Instrumentor import failed; continuing without tracing")

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=_rearm_after_fork)

    _configured = True
    return trace.get_tracer_provider()


def _rearm_after_fork(provider=None) -> None:
    """Give a forked child process a working export pipeline.

    Threads do not survive fork(): a BatchSpanProcessor inherited from the
    parent has no worker thread, so spans queued in the child are never
    exported — and the inherited exporter may hold connection-pool locks
    seized at fork time. Swap every stale batch processor for a fresh one
    with a fresh exporter; the child's spans (and its atexit flush) then
    work. Registration happens once in setup_telemetry().
    """
    if provider is None:
        provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        return
    multi = getattr(provider, "_active_span_processor", None)
    if multi is None or not hasattr(multi, "_span_processors"):
        return
    keep = []
    for proc in multi._span_processors:
        if isinstance(proc, BatchSpanProcessor):
            # Its worker thread died in the fork; queued spans are lost, and
            # its atexit flush would use the poisoned parent exporter.
            atexit.unregister(proc.shutdown)
        else:
            keep.append(proc)
    multi._span_processors = (*keep, BatchSpanProcessor(build_span_exporter()))


def _instrumentors():
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
    from opentelemetry_instrumentation_rq import RQInstrumentor

    return [
        ("rq", RQInstrumentor()),
        # Covers PostgreSQL via SQLAlchemy engines. psycopg2 instrumentation is
        # deliberately skipped: it sits beneath SQLAlchemy and would duplicate spans.
        ("sqlalchemy", SQLAlchemyInstrumentor()),
        # Covers sqlite-utils per-site DBs (meetings.db inserts, FTS rebuilds).
        ("sqlite3", SQLite3Instrumentor()),
        ("httpx", HTTPXClientInstrumentor()),
    ]
