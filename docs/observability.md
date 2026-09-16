# Observability (VictoriaTraces / VictoriaLogs / VictoriaMetrics)

Clerk jobs emit OpenTelemetry traces (OTLP/HTTP → VictoriaTraces), JSON logs on stdout (shipped by an external Vector container → VictoriaLogs, config at `deployment/vector/vector.toml`), and Prometheus metrics at per-worker-type `/metrics` endpoints (scraped by VictoriaMetrics). Each pipeline run is identified by a `run_id` that threads through traces (baggage), logs (structured field), and the `job_tracking` DB table — letting you string a complete run together in Grafana three different ways.

## Stack endpoints

| Service | HTTP port | Ingest |
|---|---|---|
| VictoriaTraces | 10428 | OTLP/HTTP at `/insert/opentelemetry/v1/traces` |
| VictoriaLogs | 9428 | Elasticsearch API at `/insert/elasticsearch/` (Vector ships here) |
| VictoriaMetrics | 8428 | Standard Prometheus scrape |

VictoriaTraces implements the Jaeger Query JSON API, so Grafana's **Jaeger datasource** works against it directly — no special plugin needed.

## Clerk configuration

Tracing is configured in `src/clerk/telemetry.py`. `setup_telemetry()` runs at CLI import time and is **never fatal if VictoriaTraces is down** — the `BatchSpanProcessor` simply drops spans it cannot export, so workers keep running.

- `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` — OTLP/HTTP endpoint for trace export. Default: `http://localhost:10428/insert/opentelemetry/v1/traces`. Set per-deployment in `.env`; the docker-compose default is `http://victoria-traces:10428/insert/opentelemetry/v1/traces`.
- `OTEL_SERVICE_NAME` — service name attached to traces. Default: `clerk`.

### Metrics

Each `clerk worker <type>` process serves `/metrics` on a per-worker-type port:

| Worker type | Default port |
|---|---|
| fetch | 9801 |
| ocr | 9802 |
| compilation | 9803 |
| extraction | 9804 |
| deploy | 9805 |

Override the port with `METRICS_PORT`. The metrics server starts even with `-n 0` workers, so an idle deployment still reports queue depth. Multiple workers per type (`-n N`) aggregate via prometheus_client multiprocess mode (`PROMETHEUS_MULTIPROC_DIR`, a tmpfs mount in compose).

Metrics exported:

- `clerk_jobs_total{stage, job_type, status}` — counter of processed RQ jobs
- `clerk_job_duration_seconds{stage, job_type}` — histogram of job durations
- `clerk_queue_depth{queue}` — gauge of pending jobs, read live from Redis at scrape time, for all 7 RQ queues (`high`, `fetch`, `ocr`, `compilation`, `extraction`, `deploy`, `finance`)

## Grafana datasources

1. **VictoriaMetrics** — Prometheus-type datasource, URL `http://<vm-host>:8428`.
2. **VictoriaLogs** — URL `http://<vlogs-host>:9428`.
3. **Traces** — **Jaeger-type datasource** (VictoriaTraces speaks the Jaeger Query JSON API), URL `http://<vtraces-host>:10428`.

## VictoriaMetrics scrape config

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

## Log shipping (Vector)

Clerk emits one JSON object per log line on stdout. A Vector sidecar container (config: `deployment/vector/vector.toml`) ships those lines to VictoriaLogs:

1. **docker source** — collects container logs from the Docker daemon.
2. **remap transform** — filters to clerk containers (container name must contain `clerk`), then flattens the JSON log line so every structured field is individually queryable in VictoriaLogs.
3. **elasticsearch sink** — sends to VictoriaLogs' Elasticsearch-compatible ingest API.

The endpoint defaults to `http://localhost:9428/insert/elasticsearch/` and can be overridden with the `VICTORIALOGS_URL` env var (bash-style default syntax: `${VICTORIALOGS_URL-http://localhost:9428}/insert/elasticsearch/`).

Field mapping (configured in the sink's `query` params):

- `_msg_field=message` — clerk's message field
- `_time_field=timestamp` — ISO-8601 timestamp from clerk's `JsonFormatter`
- `_stream_fields=container_name,level,stage` — fields used as log stream labels

## Correlating logs and traces

- **Trace → logs**: In the Jaeger datasource settings, configure "Trace to logs" targeting the VictoriaLogs datasource with a LogsQL query like `{run_id="${__span.tags.clerk.run_id}"}`. NOTE: the exact `${__span.tags...}` variable syntax varies by Grafana version — verify against your Grafana version's docs.
- **Logs → traces**: In the VictoriaLogs datasource settings, add a **derived field**: field `trace_id` → internal link to Explore with the Jaeger datasource, `traceID=${__value.raw}`.
- Every log line carries `trace_id`/`span_id` (32/16 hex chars, zeros when no active span) injected from the active OTel span, plus `run_id`, `subdomain`, `stage`, and `job_id`.

## Stringing a run together by run_id

`run_id` format: `{subdomain}_{unix_timestamp}_{6-char-random}` (generated in `src/clerk/queue.py::generate_run_id`). Three correlation paths:

1. **Traces**: every span in every job of a run carries `clerk.run_id` (OTel baggage, stamped by `BaggageSpanProcessor`). In Explore with the Jaeger/VictoriaTraces datasource, search spans by tag `clerk.run_id=<run_id>`. Each job is its own trace (fetch is the root; the OCR fan-out intentionally breaks into separate traces via `detached_trace()`), so a "run" = a set of traces sharing the baggage attribute.
2. **Logs**: LogsQL in VictoriaLogs Explore:

   ```
   {run_id="<run_id>"} | sort by (_time)
   ```

3. **Database**: the `job_tracking` table (PostgreSQL) has an indexed `run_id` column:

   ```sql
   SELECT * FROM job_tracking WHERE run_id = '<run_id>' ORDER BY created_at;
   ```

   Usable directly in a Grafana Postgres table panel.

## Useful MetricsQL

Failed jobs by stage:

```
sum by (stage) (rate(clerk_jobs_total{status="failed"}[5m]))
```

p95 job duration by stage:

```
histogram_quantile(0.95, sum by (le, stage) (rate(clerk_job_duration_seconds_bucket[5m])))
```

Queue backlog:

```
clerk_queue_depth{queue="ocr"}
```
