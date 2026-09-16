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

    assert JOBS_TOTAL._labelnames == ("stage", "job_type", "status")
    assert JOB_DURATION._labelnames == ("stage", "job_type")
    JOBS_TOTAL.labels(stage="ocr", job_type="ocr_document_job", status="success").inc()
    JOB_DURATION.labels(stage="ocr", job_type="ocr_document_job").observe(0.5)


@pytest.mark.unit
def test_multiprocess_registry_exposes_job_counters():
    from prometheus_client import CollectorRegistry
    from prometheus_client.multiprocess import MultiProcessCollector

    import clerk.metrics as metrics

    metrics.configure_multiprocess_dir()
    JOBS_TOTAL = metrics.JOBS_TOTAL
    JOBS_TOTAL.labels(stage="deploy", job_type="test_job", status="success").inc()

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
    assert samples == [({"stage": "deploy", "job_type": "test_job", "status": "success"}, 1.0)]


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
