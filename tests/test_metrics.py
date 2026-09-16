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

    assert JOBS_TOTAL._labelnames == ("container", "stage", "job_type", "status")
    assert JOB_DURATION._labelnames == ("container", "stage", "job_type")
    JOBS_TOTAL.labels(
        container="c1", stage="ocr", job_type="ocr_document_job", status="success"
    ).inc()
    JOB_DURATION.labels(container="c1", stage="ocr", job_type="ocr_document_job").observe(0.5)


@pytest.mark.unit
def test_multiprocess_registry_exposes_job_counters():
    from prometheus_client import CollectorRegistry
    from prometheus_client.multiprocess import MultiProcessCollector

    import clerk.metrics as metrics

    metrics.configure_multiprocess_dir()
    JOBS_TOTAL = metrics.JOBS_TOTAL
    JOBS_TOTAL.labels(container="c1", stage="deploy", job_type="test_job", status="success").inc()

    registry = CollectorRegistry()
    MultiProcessCollector(registry)
    samples = [
        (s.labels, s.value)
        for f in registry.collect()
        if f.name == "clerk_jobs"
        for s in f.samples
        if s.labels.get("stage") == "deploy"
        and s.labels.get("job_type") == "test_job"
        and s.labels.get("status") == "success"
    ]
    assert samples == [
        ({"container": "c1", "stage": "deploy", "job_type": "test_job", "status": "success"}, 1.0)
    ]


@pytest.mark.unit
def test_record_job_metrics_writes_container_label(tmp_path, monkeypatch):
    import prometheus_client
    from prometheus_client.multiprocess import MultiProcessCollector

    import clerk.metrics as metrics

    # Force multiprocess value class and point new labelsets at a fresh dir
    prometheus_client.values.ValueClass = prometheus_client.values.get_value_class()
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    monkeypatch.setattr(metrics, "CONTAINER_ID", "test-container-abc")

    metrics.record_job_metrics(
        stage="ocr", job_type="clerk.workers.ocr_job", status="success", duration_seconds=1.5
    )

    registry = prometheus_client.CollectorRegistry()
    MultiProcessCollector(registry, str(tmp_path))

    job_samples = [
        s
        for f in registry.collect()
        if f.name == "clerk_jobs"
        for s in f.samples
        if s.labels.get("stage") == "ocr"
    ]
    assert len(job_samples) == 1
    assert job_samples[0].labels["container"] == "test-container-abc"
    assert job_samples[0].labels["job_type"] == "clerk.workers.ocr_job"
    assert job_samples[0].labels["status"] == "success"
    assert job_samples[0].value == 1.0

    duration_samples = [
        s
        for f in registry.collect()
        if f.name == "clerk_job_duration_seconds"
        for s in f.samples
        if s.labels.get("container") == "test-container-abc"
    ]
    assert duration_samples, "histogram samples should carry the container label"


@pytest.mark.unit
def test_sweep_dead_pid_files_removes_dead_keeps_live(tmp_path, monkeypatch):
    """Files whose pid is dead are unlinked; live/other-error files are kept."""
    import clerk.metrics as metrics

    # Real filename format: {typ}_{pid}.db (counters/histograms) and
    # gauge_{mode}_{pid}.db (gauges) — see prometheus_client/values.py.
    (tmp_path / "counter_111.db").write_bytes(b"x")
    (tmp_path / "gauge_all_111.db").write_bytes(b"x")
    (tmp_path / "counter_222.db").write_bytes(b"x")
    (tmp_path / "counter_333.db").write_bytes(b"x")
    (tmp_path / "garbage.db").write_bytes(b"x")  # unparsable name: skipped

    def fake_kill(pid, sig):
        if pid == 111:
            raise ProcessLookupError(pid)  # dead
        if pid == 222:
            raise PermissionError(pid)  # alive (not ours): keep
        if pid == 333:
            raise ValueError("unexpected")  # other error: skip file
        return None

    monkeypatch.setattr(metrics.os, "kill", fake_kill)

    removed = metrics.sweep_dead_pid_files(str(tmp_path))

    assert removed == 2
    names = sorted(p.name for p in tmp_path.iterdir())
    assert "counter_111.db" not in names
    assert "gauge_all_111.db" not in names
    assert "counter_222.db" in names
    assert "counter_333.db" in names
    assert "garbage.db" in names


@pytest.mark.unit
def test_sweep_dead_pid_files_defaults_to_env_dir(tmp_path, monkeypatch):
    import clerk.metrics as metrics

    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    (tmp_path / "counter_111.db").write_bytes(b"x")

    def fake_kill(pid, sig):
        raise ProcessLookupError(pid)

    monkeypatch.setattr(metrics.os, "kill", fake_kill)

    assert metrics.sweep_dead_pid_files() == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.unit
def test_build_aggregated_registry_includes_multiproc_and_queue_depth(tmp_path, monkeypatch):
    import prometheus_client
    import redis

    import clerk.metrics as metrics

    prometheus_client.values.ValueClass = prometheus_client.values.get_value_class()
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    monkeypatch.setattr(metrics, "CONTAINER_ID", "test-container-abc")

    def _no_redis():
        raise redis.ConnectionError("no redis")

    monkeypatch.setattr("clerk.queue.get_redis", _no_redis)
    metrics.record_job_metrics(
        stage="deploy", job_type="clerk.workers.deploy_job", status="success", duration_seconds=0.2
    )

    registry = metrics.build_aggregated_registry(str(tmp_path))

    names = [f.name for f in registry.collect()]
    assert "clerk_jobs" in names
    assert "clerk_job_duration_seconds" in names
    assert "clerk_queue_depth" in names


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
    families = list(collector.collect())
    assert families[0].name == "clerk_queue_depth"
    assert families[0].samples == []
