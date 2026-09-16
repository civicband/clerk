# Clerk Observability: VictoriaTraces / VictoriaLogs / VictoriaMetrics

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every clerk job becomes a distinct trace (with child spans) in Grafana via VictoriaTraces, every log line carries `trace_id`/`run_id` and ships to VictoriaLogs via the existing Vector container, and workers expose Prometheus metrics scraped by VictoriaMetrics — with a complete pipeline run strung together by `run_id`.

**Architecture:** Clerk is already ~80% OTel-wired (spans wrap every job, `BaggageSpanProcessor` stamps `clerk.run_id` onto every span, `detached_trace()` makes OCR fan-out new traces) but has no exporter. This plan adds: (1) an explicit OTLP/HTTP exporter to VictoriaTraces plus Redis/SQLAlchemy/httpx auto-instrumentation for subtraces; (2) a logging filter that injects `trace_id`/`span_id` into the existing JSON logs so Vector → VictoriaLogs correlates logs-to-traces; (3) `prometheus_client` in multiprocess mode served at per-worker-type `/metrics` endpoints, with a Redis queue-depth collector; (4) `run_id` persisted in `job_tracking` for DB-level correlation. Victoria stack itself is deployed separately; this repo ships code + `deployment/vector/vector.toml` + Grafana wiring docs.

**Tech Stack:** OpenTelemetry SDK (already a dep), `prometheus-client` (new), Vector Elasticsearch sink → VictoriaLogs, VictoriaTraces port 10428, VictoriaLogs port 9428, VictoriaMetrics port 8428.

---

## Task 1: Remove dead Loki path

**Files:**
- Modify: `pyproject.toml` (remove `python-logging-loki`)
- Modify: `.env.example` (remove LOKI block, lines 55-59)
- Modify: `src/clerk/settings.py` (~line 169, remove `LOKI_URL`)
- Modify: `src/clerk/output.py` (Loki mentions at ~lines 68, 128, 184) and `src/clerk/cli.py:51` (fix "Loki" docstrings/help text → "logs are shipped via Vector to VictoriaLogs")

- [ ] Grep for `loki|LOKI` across `src/`, `.env.example`, `pyproject.toml`; remove the dependency line, env var, setting, and rewrite the three docstrings/help strings.
- [ ] Run: `uv lock && uv sync && just test` — expected: all tests pass (nothing imports `python_logging_loki`).
- [ ] Run: `just lint && just typecheck`
- [ ] Commit: `chore: remove dead Loki log-shipping path`

## Task 2: Inject trace context + ISO timestamps into JSON logs

**Files:**
- Modify: `src/clerk/output.py`
- Test: `tests/test_output.py`

- [ ] **Write failing tests** in `tests/test_output.py`:

```python
def test_json_formatter_includes_trace_fields():
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    trace.set_tracer_provider(TracerProvider())
    tracer = trace.get_tracer("test")
    fmt = output.JsonFormatter()
    rec = logging.LogRecord("t", logging.INFO, "p", 1, "hello", None, None)
    with tracer.start_as_current_span("s") as span:
        expected_trace = format(span.get_span_context().trace_id, "032x")
        expected_span = format(span.get_span_context().span_id, "016x")
        data = json.loads(fmt.format(rec))
    assert data["trace_id"] == expected_trace
    assert data["span_id"] == expected_span

def test_json_formatter_zero_trace_ids_without_active_span():
    fmt = output.JsonFormatter()
    rec = logging.LogRecord("t", logging.INFO, "p", 1, "hello", None, None)
    data = json.loads(fmt.format(rec))
    assert data["trace_id"] == "0" * 32
    assert data["span_id"] == "0" * 16

def test_json_formatter_timestamp_is_iso8601_utc():
    fmt = output.JsonFormatter()
    rec = logging.LogRecord("t", logging.INFO, "p", 1, "hello", None, None)
    data = json.loads(fmt.format(rec))
    parsed = datetime.fromisoformat(data["timestamp"])
    assert parsed.tzinfo is not None
```

- [ ] Run: `uv run python -m pytest tests/test_output.py -m unit -v` — expected: FAIL (no `trace_id` key).
- [ ] **Implement** in `output.py`: add imports `from datetime import UTC, datetime` and `from opentelemetry import trace`, then:

```python
class TraceContextFilter(logging.Filter):
    """Inject the active OTel span context into every record as trace_id/span_id."""

    def filter(self, record):
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            record.trace_id = format(span_context.trace_id, "032x")
            record.span_id = format(span_context.span_id, "016x")
        else:
            record.trace_id = "0" * 32
            record.span_id = "0" * 16
        return True
```

In `JsonFormatter.format`, replace the timestamp line with
`"timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),`
In `configure_logging`, attach the filter to the **handler** (logger filters don't apply to propagated records):

```python
    console = logging.StreamHandler()
    console.setFormatter(JsonFormatter())
    console.addFilter(TraceContextFilter())
```

- [ ] Run: `uv run python -m pytest tests/test_output.py -m unit -v` — expected: PASS.
- [ ] Run: `just test && just check`. Commit: `feat: add trace context and ISO-8601 timestamps to JSON logs`

## Task 3: `telemetry.py` — OTLP export to VictoriaTraces

**Files:**
- Create: `src/clerk/telemetry.py`
- Modify: `src/clerk/cli.py` (replace the ad-hoc RQInstrumentor/BaggageSpanProcessor block at lines 27-36)
- Test: `tests/test_telemetry.py`

- [ ] **Write failing tests**:

```python
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.processor.baggage import BaggageSpanProcessor
from opentelemetry.sdk.trace.export import BatchSpanProcessor


@pytest.mark.unit
def test_setup_telemetry_configures_provider_with_endpoint(monkeypatch):
    import clerk.telemetry as telemetry
    monkeypatch.setattr(telemetry, "_configured", False)
    endpoint = "http://vtraces.test:10428/insert/opentelemetry/v1/traces"
    provider = telemetry.setup_telemetry(endpoint=endpoint, service_name="clerk-test")
    assert isinstance(provider, TracerProvider)
    assert provider.resource.attributes["service.name"] == "clerk-test"
    processors = provider._active_span_processor._span_processors
    assert any(isinstance(p, BaggageSpanProcessor) for p in processors)
    assert any(isinstance(p, BatchSpanProcessor) for p in processors)


@pytest.mark.unit
def test_setup_telemetry_is_idempotent(monkeypatch):
    import clerk.telemetry as telemetry
    monkeypatch.setattr(telemetry, "_configured", False)
    p1 = telemetry.setup_telemetry(endpoint="http://x:10428/insert/opentelemetry/v1/traces")
    p2 = telemetry.setup_telemetry(endpoint="http://x:10428/insert/opentelemetry/v1/traces")
    assert p1 is p2
```

- [ ] Run: `uv run python -m pytest tests/test_telemetry.py -m unit -v` — expected: FAIL (module missing).
- [ ] **Implement** `src/clerk/telemetry.py`:

```python
"""OpenTelemetry setup: traces exported to VictoriaTraces via OTLP/HTTP."""

import logging
import os

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
            "service.name": service_name
            or os.environ.get("OTEL_SERVICE_NAME", "clerk"),
            "service.version": __version__,
        }
    )


def build_span_exporter(endpoint: str | None = None) -> OTLPSpanExporter:
    url = endpoint or os.environ.get(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", DEFAULT_TRACES_ENDPOINT
    )
    return OTLPSpanExporter(url=url, timeout=5)


def setup_telemetry(endpoint: str | None = None, service_name: str | None = None):
    """Configure the global TracerProvider + instrumentations. Idempotent.

    Non-fatal on failure: workers must run even if VictoriaTraces is unreachable
    (BatchSpanProcessor drops spans it cannot export).
    """
    global _configured
    if _configured:
        return trace.get_tracer_provider()
    try:
        provider = TracerProvider(resource=build_resource(service_name))
        provider.add_span_processor(BaggageSpanProcessor(ALLOW_ALL_BAGGAGE_KEYS))
        provider.add_span_processor(BatchSpanProcessor(build_span_exporter(endpoint)))
        trace.set_tracer_provider(provider)

        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        from opentelemetry.instrumentation.rq import RQInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        RQInstrumentor().instrument()
        RedisInstrumentor().instrument()
        SQLAlchemyInstrumentor().instrument()
        HTTPXClientInstrumentor().instrument()
        _configured = True
        return provider
    except Exception:  # pragma: no cover - never break workers on telemetry setup
        logger.exception("Telemetry setup failed; continuing without tracing")
        return trace.get_tracer_provider()
```

Notes: deliberately do **not** instrument `requests`/`urllib3` (avoids export-recursion noise), and do **not** call `LoggingInstrumentor` (Task 2 handles log correlation ourselves).

- [ ] **Rewire `cli.py`**: delete lines 27-36 (RQInstrumentor import/instrument, trace/BaggageSpanProcessor block) and place immediately after `load_dotenv(find_dotenv())` and **before** `from .db import db` (so SQLAlchemy engines are created after instrumentation):

```python
from .telemetry import setup_telemetry

setup_telemetry()
```

(Keep the `# ruff: noqa: E402` pragma covering these import-time statements.)

- [ ] Run: `uv run python -m pytest tests/test_telemetry.py tests/test_cli.py -m unit -v` — expected: PASS (fix `tests/test_cli.py` fixtures that referenced the removed block if needed).
- [ ] Commit: `feat: export OTel traces to VictoriaTraces via OTLP/HTTP`

## Task 4: `metrics.py` — Prometheus metrics in multiprocess mode

**Files:**
- Create: `src/clerk/metrics.py`
- Modify: `pyproject.toml` deps (add `"prometheus-client>=0.21"`)
- Test: `tests/test_metrics.py`

- [ ] Add dependency: `prometheus-client>=0.21` to `[project] dependencies`; `uv lock && uv sync`.
- [ ] **Write failing tests**:

```python
import os
from pathlib import Path

import pytest


@pytest.mark.unit
def test_configure_multiprocess_dir_sets_env(monkeypatch):
    import clerk.metrics as metrics
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
    d = metrics.configure_multiprocess_dir()
    assert os.environ["PROMETHEUS_MULTIPROC_DIR"] == d
    assert Path(d).is_dir()


@pytest.mark.unit
def test_job_counters_have_expected_labels():
    from clerk.metrics import JOB_DURATION, JOBS_TOTAL
    JOBS_TOTAL.labels(stage="ocr", job_type="ocr_document_job", status="success").inc()
    JOB_DURATION.labels(stage="ocr", job_type="ocr_document_job").observe(0.5)


@pytest.mark.unit
def test_queue_depth_collector_yields_gauge():
    from clerk.metrics import QueueDepthCollector
    collector = QueueDepthCollector(
        queue_names=["fetch", "ocr"], count_fn=lambda n: {"fetch": 3, "ocr": 0}[n]
    )
    families = list(collector.collect())
    assert families[0].name == "clerk_queue_depth"
    samples = {s.labels["queue"]: s.value for s in families[0].samples}
    assert samples == {"fetch": 3.0, "ocr": 0.0}


@pytest.mark.unit
def test_queue_depth_collector_swallows_redis_errors():
    from clerk.metrics import QueueDepthCollector

    def boom(name):
        raise ConnectionError("redis down")

    collector = QueueDepthCollector(queue_names=["fetch"], count_fn=boom)
    families = list(collector.collect())  # yields the family with no samples
    assert families[0].name == "clerk_queue_depth"
    assert families[0].samples == []
```

- [ ] Run: `uv run python -m pytest tests/test_metrics.py -m unit -v` — expected: FAIL.
- [ ] **Implement** `src/clerk/metrics.py`:

```python
"""Prometheus metrics for clerk workers, exposed for VictoriaMetrics scraping.

Uses prometheus_client multiprocess mode so that RQ WorkerPool children
(`clerk worker ocr -n 4`) all contribute to one /metrics endpoint per container.
"""

import os
import tempfile

from prometheus_client import CollectorRegistry, Counter, GaugeMetricFamily, Histogram
from prometheus_client.multiprocess import MultiProcessCollector

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
    return mp_dir


configure_multiprocess_dir()

JOBS_TOTAL = Counter(
    "clerk_jobs_total", "RQ jobs processed", ["stage", "job_type", "status"]
)
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
        gauge = GaugeMetricFamily(
            "clerk_queue_depth", "Pending jobs in RQ queue", labels=["queue"]
        )
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
                continue  # Redis down / queue missing: emit nothing for it
        yield gauge


def start_metrics_server(port: int):
    """Start /metrics on `port`, aggregating multiprocess files + queue depth."""
    from prometheus_client import start_http_server

    registry = CollectorRegistry()
    MultiProcessCollector(registry)
    registry.register(QueueDepthCollector())
    server, thread = start_http_server(port, registry=registry)
    return server
```

- [ ] Run: `uv run python -m pytest tests/test_metrics.py -m unit -v` — expected: PASS.
- [ ] Commit: `feat: add prometheus metrics module with queue depth collector`

## Task 5: Worker command starts metrics server + records job outcomes

**Files:**
- Modify: `src/clerk/cli.py` (`worker` command, `DiagnosticWorker`, lines ~87-161)
- Test: `tests/test_cli.py`

- [ ] **Write failing test** (adapt to existing `cli_module` fixture patterns in `tests/test_cli.py`):

```python
@pytest.mark.unit
def test_worker_command_starts_metrics_server(cli_module, monkeypatch):
    calls = {}
    monkeypatch.setattr(
        "clerk.metrics.start_metrics_server", lambda port: calls.setdefault("port", port)
    )
    monkeypatch.setattr("rq.Worker.work", lambda self, **kw: None)
    runner = CliRunner()
    runner.invoke(cli_module.cli, ["worker", "ocr", "--burst"], catch_exceptions=False)
    assert calls["port"] == 9802


@pytest.mark.unit
def test_perform_job_records_metrics(monkeypatch):
    # DiagnosticWorker.perform_job must increment JOBS_TOTAL and observe JOB_DURATION
    # for both success and failure paths. Mock super().perform_job.
    ...
```

- [ ] Run: `uv run python -m pytest tests/test_cli.py -m unit -v` — expected: FAIL.
- [ ] **Implement** in `cli.py`:

In `DiagnosticWorker`, record job outcomes at the single choke point that covers **all** jobs including plugin jobs:

```python
    def perform_job(self, job, queue) -> bool:
        """Override to record job metrics, then delegate to RQ."""
        import time

        from .metrics import JOB_DURATION, JOBS_TOTAL

        stage = queue.name
        job_type = job.func_name
        status = "failed"
        start = time.monotonic()
        try:
            result = super().perform_job(job, queue)
            status = "success" if result else "failed"
            return result
        finally:
            try:
                JOB_DURATION.labels(stage=stage, job_type=job_type).observe(
                    time.monotonic() - start
                )
                JOBS_TOTAL.labels(stage=stage, job_type=job_type, status=status).inc()
            except Exception:
                pass
```

In the `worker` command body, before the `num_workers == 0` early return:

```python
    from .metrics import METRICS_PORTS, start_metrics_server

    metrics_port = int(os.environ.get("METRICS_PORT", METRICS_PORTS[worker_type]))
    try:
        start_metrics_server(metrics_port)
    except OSError:
        click.secho(f"Warning: metrics port {metrics_port} unavailable, continuing", fg="yellow")
```

- [ ] Run: `uv run python -m pytest tests/test_cli.py tests/test_metrics.py -m unit -v` — expected: PASS.
- [ ] Run: `just test && just check`. Commit: `feat: expose per-worker /metrics and record job outcomes`

## Task 6: Persist `run_id` in `job_tracking`

**Files:**
- Modify: `src/clerk/models.py` (job_tracking_table, lines 68-76: add `run_id` column + index)
- Create: `alembic/versions/<rev>_add_run_id_to_job_tracking.py`
- Modify: `src/clerk/queue_db.py` (`track_job`, `track_jobs_bulk`, lines 10-59)
- Modify: `src/clerk/workers.py` — pass `run_id` at the `track_job` call (~line 341) and the `track_jobs_bulk` call in `fetch_site_job` (~line 160); grep `track_job(|track_jobs_bulk(` for remaining call sites and pass `run_id` where in scope
- Test: `tests/test_queue_db.py`

- [ ] **Write failing tests** (follow the existing connection fixture patterns in `tests/test_queue_db.py`):

```python
def test_track_job_stores_run_id(...):
    track_job(conn, "rq-123", "springfield", "fetch-site", "fetch", run_id="springfield_1_abc")
    rows = get_jobs_for_site(conn, "springfield")
    assert rows[0]["run_id"] == "springfield_1_abc"


def test_track_jobs_bulk_stores_run_id(...):
    track_jobs_bulk(conn, [fake_job_1, fake_job_2], "springfield", "ocr-page", "ocr", run_id="springfield_1_abc")
    assert all(r["run_id"] == "springfield_1_abc" for r in rows)
```

- [ ] Run: `uv run python -m pytest tests/test_queue_db.py -m unit -v` — expected: FAIL (unexpected kwarg).
- [ ] **Implement**: add to `job_tracking_table`:

```python
    sa.Column("run_id", sa.String(), nullable=True),
```

plus an index on `run_id` (match the existing index style in the table). Migration (generate with `uv run alembic revision -m "add run_id to job_tracking"`, then fill in; set the down_revision to the current head):

```python
def upgrade():
    op.add_column("job_tracking", sa.Column("run_id", sa.String(), nullable=True))
    op.create_index("ix_job_tracking_run_id", "job_tracking", ["run_id"])


def downgrade():
    op.drop_index("ix_job_tracking_run_id", table_name="job_tracking")
    op.drop_column("job_tracking", "run_id")
```

Update `track_job`/`track_jobs_bulk` signatures to `..., run_id: str | None = None` and include `"run_id": run_id` in the insert values. Update callers to pass `run_id`.
- [ ] Run: `uv run python -m pytest tests/test_queue_db.py tests/test_db.py tests/test_workers.py -m unit -v` — expected: PASS.
- [ ] Commit: `feat: persist run_id in job_tracking for run-level correlation`

## Task 7: Deployment config — compose env, ports, tmpfs

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

- [ ] Update `.env.example` — replace the removed Loki block with:

```bash
# Observability
# VictoriaTraces OTLP/HTTP ingest endpoint (spans)
# VictoriaTraces default HTTP port is 10428
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:10428/insert/opentelemetry/v1/traces
OTEL_SERVICE_NAME=clerk
# Sample 100% of traces in dev; lower in prod if needed (e.g. parentbased_traceidratio)
# OTEL_TRACES_SAMPLER=parentbased_always_on
# Per-worker-type Prometheus metrics port (VictoriaMetrics scrapes these)
# Overrides: METRICS_PORT applies to any worker; defaults 9801-9805 by type
```

- [ ] Update `docker-compose.yml` common anchor:

```yaml
x-common-settings: &common-settings
  build: .
  env_file: .env
  restart: on-failure
  environment:
    - STORAGE_DIR=/clerk_sites
    - OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=${OTEL_EXPORTER_OTLP_TRACES_ENDPOINT:-http://victoria-traces:10428/insert/opentelemetry/v1/traces}
    - OTEL_SERVICE_NAME=clerk
    - PROMETHEUS_MULTIPROC_DIR=/tmp/clerk-prom
  tmpfs:
    - /tmp/clerk-prom
  volumes:
    - ${STORAGE_DIR}:/clerk_sites/
    - .:/app
  networks:
    - clerk
```

and per service, expose the metrics port:

```yaml
  fetch_worker:
    <<: *common-settings
    command: clerk worker fetch -n ${FETCH_WORKERS}
    ports: ["9801:9801"]
```

(ocr → 9802, compilation → 9803, deploy → 9805.)

- [ ] Sanity: `docker compose config` parses cleanly.
- [ ] Commit: `chore: wire trace export + metrics ports into docker-compose`

## Task 8: Vector config for VictoriaLogs

**Files:**
- Create: `deployment/vector/vector.toml`

- [ ] **Implement** (Vector v0.39+ TOML syntax; if your installed Vector rejects TOML, the content maps 1:1 to `vector.yaml`):

```toml
# Ship clerk Docker container logs to VictoriaLogs.
# Run with: vector --config /etc/vector/vector.toml
data_dir = "/var/lib/vector"

sources:
  clerk_docker:
    type: docker
    exclude_containers: ["^vector"]

transforms:
  clerk_logs:
    type: remap
    inputs: ["clerk_docker"]
    source: '''
      if !contains(to_string(.container_name) ?? "", "clerk") {
        abort
      }
      # Clerk emits JSON lines on stdout; flatten so each field is queryable
      parsed, err = parse_json(to_string(.message) ?? "")
      if err == null && is_object(parsed) {
        . = merge(., parsed)
      }
      .host = get_hostname!()
    '''

sinks:
  vlogs:
    type: elasticsearch
    inputs: ["clerk_logs"]
    endpoints: ["${VICTORIALOGS_URL:-http://localhost:9428}/insert/elasticsearch/"]
    api_version: v8
    compression: gzip
    healthcheck:
      enabled: false
    query:
      _msg_field: message
      _time_field: timestamp
      _stream_fields: container_name,level,stage
      # debug: "1"   # uncomment once to verify field mapping in VLogs logs
```

The ISO-8601 `timestamp` from Task 2 is what makes `_time_field=timestamp` parse correctly; `trace_id`, `span_id`, `run_id`, `subdomain`, `stage`, `job_id` arrive as regular fields — exactly what Grafana trace-to-log correlation needs.
- [ ] Validate locally if you have vector: `vector validate --no-environment deployment/vector/vector.toml`
- [ ] Commit: `feat: add vector config shipping clerk docker logs to VictoriaLogs`

## Task 9: Grafana wiring + VictoriaMetrics scrape docs

**Files:**
- Create: `docs/observability.md`

- [ ] Write `docs/observability.md` covering (exact content, not placeholders):

1. **Datasources** (Grafana):
   - VictoriaMetrics: Prometheus-type, URL `http://<vm>:8428`
   - VictoriaLogs: URL `http://<vlogs>:9428`
   - **Traces: Jaeger-type datasource** (VictoriaTraces implements the Jaeger Query JSON API), URL `http://<vtraces>:10428`
2. **VM scrape config** for worker metrics:

```yaml
scrape_configs:
  - job_name: clerk-workers
    static_configs:
      - targets:
          - "clerk-host:9801"  # fetch
          - "clerk-host:9802"  # ocr
          - "clerk-host:9803"  # compilation
          - "clerk-host:9804"  # extraction
          - "clerk-host:9805"  # deploy
```

3. **Trace-to-logs** (Grafana → Jaeger datasource settings → Trace to logs): target the VictoriaLogs datasource, query `{run_id="${__span.tags.clerk.run_id}"}` (span attrs from baggage). NOTE: the exact `${__span.tags...}` variable syntax varies slightly by Grafana version — verify against your Grafana version.
4. **Logs-to-traces** (VictoriaLogs datasource → Derived fields): field `trace_id` → internal link to Explore with the Jaeger datasource, `traceID=${__value.raw}`.
5. **Stringing a run together by run_id** — three ways:
   - Traces: in Explore (Jaeger/VTraces datasource) search by tag `clerk.run_id=<run_id>`; because every span (including child redis/sqlalchemy/httpx spans) inherits baggage, the whole run is retrievable; each job is its own trace (fetch is root; OCR fan-out uses `detached_trace()`).
   - Logs: LogsQL `{run_id="<run_id>"} | sort by (_time)` in VictoriaLogs Explore.
   - Postgres: `SELECT * FROM job_tracking WHERE run_id = '<run_id>' ORDER BY created_at` (Task 6) — table panel via the Postgres datasource.
6. **MetricsQL examples**: `sum by (stage) (rate(clerk_jobs_total{status="failed"}[5m]))`, `histogram_quantile(0.95, sum by (le, stage) (rate(clerk_job_duration_seconds_bucket[5m])))`, `clerk_queue_depth{queue="ocr"}`.
- [ ] Commit: `docs: grafana/victoria observability wiring guide`

## Task 10: Full verification

- [ ] `just test` — all tests pass (224+ new).
- [ ] `just check` (lint + format-check + typecheck).
- [ ] `pre-commit run --all-files`
- [ ] Manual smoke (optional, needs local Victoria stack): run `victoria-traces` + `victoria-logs` + `victoria-metrics` containers, `docker compose up redis fetch_worker`, enqueue `clerk etl update -s <site>`, confirm in Grafana: trace for `job.fetch` with `clerk.run_id` attr, `/metrics` on 9801 serving `clerk_jobs_total`, logs in VLogs Explore with `trace_id`.

---

## Design notes / self-review

- **Each job = distinct trace with subtraces**: `*_with_trace` wrappers already create a root span per job; Redis/SQLAlchemy/httpx auto-instrumentation (Task 3) supplies the child spans; `detached_trace()` keeps the OCR fan-out from creating one giant trace.
- **run_id stringing**: baggage → `clerk.run_id` span attribute on *every* span in the run (existing `BaggageSpanProcessor`), plus `trace_id` on every log line (Task 2), plus a DB column (Task 6). Three independent correlation paths.
- **Metrics multiprocess**: `PROMETHEUS_MULTIPROC_DIR` + `MultiProcessCollector` handles `clerk worker ocr -n 4` (fork) correctly; queue depth is computed live at scrape time via a custom collector, so no gauge-sync issues across forks. tmpfs keeps the multiproc dir container-local.
- **Failure isolation**: telemetry setup and metric recording are wrapped so a down Victoria stack never breaks the pipeline.
