"""Prometheus metrics for clerk workers, exposed for VictoriaMetrics scraping.

Uses prometheus_client multiprocess mode so that RQ WorkerPool children
(`clerk worker ocr -n 4`) all contribute to one /metrics endpoint per container.
"""

import logging
import os
import tempfile

from prometheus_client import CollectorRegistry, Counter, Histogram
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.multiprocess import MultiProcessCollector

logger = logging.getLogger(__name__)

METRICS_PORTS = {
    "fetch": 9801,
    "ocr": 9802,
    "compilation": 9803,
    "extraction": 9804,
    "deploy": 9805,
}

QUEUE_NAMES = ["high", "fetch", "ocr", "compilation", "extraction", "deploy", "finance"]


def configure_multiprocess_dir() -> str:
    """Ensure PROMETHEUS_MULTIPROC_DIR exists; must run before metrics are created."""
    mp_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not mp_dir:
        mp_dir = tempfile.mkdtemp(prefix="clerk-prom-")
        os.environ["PROMETHEUS_MULTIPROC_DIR"] = mp_dir
    os.makedirs(mp_dir, exist_ok=True)
    from prometheus_client import values as prometheus_values

    prometheus_values.ValueClass = prometheus_values.get_value_class()
    return mp_dir


configure_multiprocess_dir()

JOBS_TOTAL = Counter("clerk_jobs_total", "RQ jobs processed", ["stage", "job_type", "status"])
JOB_DURATION = Histogram(
    "clerk_job_duration_seconds", "RQ job duration in seconds", ["stage", "job_type"]
)


class QueueDepthCollector:
    """Gauge of pending RQ jobs per queue, read live from Redis at scrape time.

    Safe to register pre-fork: whichever forked child serves the scrape runs
    collect() fresh. count_fn is injectable for tests.
    """

    def __init__(self, queue_names=None, count_fn=None):
        self.queue_names = queue_names or QUEUE_NAMES
        self._count_fn = count_fn

    def collect(self):
        gauge = GaugeMetricFamily("clerk_queue_depth", "Pending jobs in RQ queue", labels=["queue"])
        for name in self.queue_names:
            try:
                if self._count_fn is not None:
                    value = self._count_fn(name)
                else:
                    from rq import Queue

                    from .queue import get_redis

                    value = Queue(name, connection=get_redis()).count
                gauge.add_metric([name], float(value))
            except Exception:
                logger.debug("Queue depth lookup failed for %s", name, exc_info=True)
                continue
        yield gauge


def start_metrics_server(port: int):
    """Start /metrics on `port`, aggregating multiprocess files + queue depth."""
    from prometheus_client import start_http_server

    registry = CollectorRegistry()
    MultiProcessCollector(registry)
    registry.register(QueueDepthCollector())
    server, thread = start_http_server(port, registry=registry)
    return server
