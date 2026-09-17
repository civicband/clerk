"""Prometheus metrics for clerk workers, exposed for VictoriaMetrics scraping.

Uses prometheus_client multiprocess mode so that RQ WorkerPool children
(`clerk worker ocr -n 4`) all contribute to one /metrics endpoint per container.
"""

import logging
import os
import socket
import tempfile

from prometheus_client import CollectorRegistry, Counter, Histogram
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.multiprocess import MultiProcessCollector

from .queue import QUEUE_NAMES

logger = logging.getLogger(__name__)

# Identifies which worker container wrote a metric sample. In Docker,
# socket.gethostname() is the container's hostname (short id).
CONTAINER_ID = socket.gethostname()

METRICS_PORTS = {
    "fetch": 9801,
    "ocr": 9802,
    "compilation": 9803,
    "extraction": 9804,
    "deploy": 9805,
}


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

JOBS_TOTAL = Counter(
    "clerk_jobs_total", "RQ jobs processed", ["container", "stage", "job_type", "status"]
)
JOB_DURATION = Histogram(
    "clerk_job_duration_seconds", "RQ job duration in seconds", ["container", "stage", "job_type"]
)


def record_job_metrics(stage: str, job_type: str, status: str, duration_seconds: float) -> None:
    """Record a completed job's metrics with container attribution."""
    labels = {"container": CONTAINER_ID, "stage": stage, "job_type": job_type}
    JOB_DURATION.labels(**labels).observe(duration_seconds)
    JOBS_TOTAL.labels(**labels, status=status).inc()


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
            except (Exception, SystemExit):
                # SystemExit: get_redis() calls sys.exit(1) when Redis is
                # unreachable — a Redis outage must not break serving job metrics.
                logger.debug("Queue depth lookup failed for %s", name, exc_info=True)
                continue
        yield gauge


def sweep_dead_pid_files(directory: str | None = None) -> int:
    """Remove multiproc metric files whose writer pid is no longer alive.

    Only correct when writers run with pid: host (compose does). Best-effort:
    unreadable names are skipped; pid-reuse can theoretically unlink a live
    file, which only resets that counter (rate() handles counter resets).
    Returns the number of files removed.
    """
    if directory is None:
        directory = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not directory or not os.path.isdir(directory):
        return 0

    removed = 0
    for name in os.listdir(directory):
        stem, ext = os.path.splitext(name)
        if ext != ".db" or "_" not in stem:
            continue
        pid_str = stem.rsplit("_", 1)[1]
        if not pid_str.isdigit():
            continue
        pid = int(pid_str)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            try:
                os.unlink(os.path.join(directory, name))
                removed += 1
            except OSError:
                logger.debug("Failed to unlink dead-pid metrics file %s", name, exc_info=True)
        except PermissionError:
            # Not our pid (or not permitted to signal): still alive, keep the file.
            continue
        except Exception:
            # Never fatal: skip files we cannot reason about.
            logger.debug("Skipping metrics file %s during sweep", name, exc_info=True)
    return removed


def build_aggregated_registry(directory: str | None = None) -> CollectorRegistry:
    """Registry combining shared-dir multiprocess metrics + live queue depth."""
    registry = CollectorRegistry()
    MultiProcessCollector(registry, directory)
    registry.register(QueueDepthCollector())
    return registry


def start_metrics_server(port: int):
    """Start /metrics on `port`, aggregating multiprocess files + queue depth."""
    from prometheus_client import start_http_server

    server, thread = start_http_server(port, registry=build_aggregated_registry())
    return server
