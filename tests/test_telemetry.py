"""Tests for telemetry setup."""

import pytest
from opentelemetry import trace
from opentelemetry.processor.baggage import BaggageSpanProcessor

from clerk import telemetry


class _StubSpanProcessor:
    def __init__(self, *args, **kwargs):
        pass

    def shutdown(self):
        return True

    def force_flush(self, timeout_millis=None):
        return True


class _StubExporter:
    def __init__(self, *args, **kwargs):
        pass


@pytest.fixture(autouse=True)
def reset_configured(monkeypatch):
    monkeypatch.setattr(telemetry, "_configured", False)


@pytest.fixture
def no_global_side_effects(monkeypatch):
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", _StubExporter)
    monkeypatch.setattr(telemetry, "BatchSpanProcessor", _StubSpanProcessor)
    monkeypatch.setattr(telemetry, "_instrumentors", lambda: [])


@pytest.mark.unit
def test_build_resource_has_service_name_and_version():
    resource = telemetry.build_resource()
    attrs = dict(resource.attributes)
    assert attrs["service.name"] == "clerk"
    from clerk import __version__

    assert attrs["service.version"] == __version__


@pytest.mark.unit
def test_build_resource_service_name_param_wins(monkeypatch):
    monkeypatch.setenv("OTEL_SERVICE_NAME", "from-env")
    resource = telemetry.build_resource(service_name="explicit")
    assert dict(resource.attributes)["service.name"] == "explicit"


@pytest.mark.unit
def test_build_resource_service_name_env_fallback(monkeypatch):
    monkeypatch.setenv("OTEL_SERVICE_NAME", "from-env")
    resource = telemetry.build_resource()
    assert dict(resource.attributes)["service.name"] == "from-env"


@pytest.mark.unit
def test_build_span_exporter_is_otlp_http():
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    exporter = telemetry.build_span_exporter()
    assert isinstance(exporter, OTLPSpanExporter)


@pytest.mark.unit
def test_build_span_exporter_explicit_endpoint():
    exporter = telemetry.build_span_exporter(
        endpoint="http://vtraces.test:10428/insert/opentelemetry/v1/traces"
    )
    assert exporter._endpoint == "http://vtraces.test:10428/insert/opentelemetry/v1/traces"


@pytest.mark.unit
def test_build_span_exporter_env_endpoint(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://env-endpoint:10428/traces")
    exporter = telemetry.build_span_exporter()
    assert exporter._endpoint == "http://env-endpoint:10428/traces"


@pytest.mark.unit
def test_build_span_exporter_default_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    exporter = telemetry.build_span_exporter()
    assert exporter._endpoint == telemetry.DEFAULT_TRACES_ENDPOINT


@pytest.mark.unit
def test_setup_telemetry_is_idempotent(no_global_side_effects):
    first = telemetry.setup_telemetry()
    second = telemetry.setup_telemetry()
    assert first is second
    assert telemetry._configured is True


@pytest.mark.unit
def test_build_provider_includes_baggage_processor(no_global_side_effects):
    provider = telemetry.build_provider()
    processors = provider._active_span_processor._span_processors
    assert any(isinstance(p, BaggageSpanProcessor) for p in processors)
    assert any(isinstance(p, _StubSpanProcessor) for p in processors)


@pytest.mark.unit
def test_setup_telemetry_installs_build_provider(monkeypatch, no_global_side_effects):
    installed = []
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", installed.append)
    built = telemetry.build_provider()
    monkeypatch.setattr(telemetry, "build_provider", lambda *a, **kw: built)

    telemetry.setup_telemetry()

    assert installed == [built]


@pytest.mark.unit
def test_setup_telemetry_survives_exporter_failure(monkeypatch):
    def exploding_exporter(*args, **kwargs):
        raise RuntimeError("exporter init failed")

    monkeypatch.setattr(telemetry, "OTLPSpanExporter", exploding_exporter)

    result = telemetry.setup_telemetry()
    assert result is trace.get_tracer_provider()
    assert telemetry._configured is False

    with pytest.MonkeyPatch.context() as retry_patch:
        retry_patch.setattr(telemetry, "OTLPSpanExporter", _StubExporter)
        retry_patch.setattr(telemetry, "BatchSpanProcessor", _StubSpanProcessor)
        retry_patch.setattr(telemetry, "_instrumentors", lambda: [])
        retry = telemetry.setup_telemetry()
        assert retry is trace.get_tracer_provider()
        assert telemetry._configured is True


@pytest.mark.unit
def test_setup_telemetry_survives_instrumentor_failure(monkeypatch):
    class FailingInstrumentor:
        def instrument(self):
            raise RuntimeError("instrument failed")

    class WorkingInstrumentor:
        def __init__(self):
            self.instrumented = False

        def instrument(self):
            self.instrumented = True

    working = WorkingInstrumentor()
    monkeypatch.setattr(
        telemetry,
        "_instrumentors",
        lambda: [("failing", FailingInstrumentor()), ("working", working)],
    )
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", _StubExporter)
    monkeypatch.setattr(telemetry, "BatchSpanProcessor", _StubSpanProcessor)

    result = telemetry.setup_telemetry()

    assert result is trace.get_tracer_provider()
    assert telemetry._configured is True
    assert working.instrumented is True


@pytest.mark.unit
def test_setup_telemetry_survives_instrumentors_import_failure(monkeypatch):
    def missing_instrumentors():
        raise ImportError("instrumentation package not installed")

    monkeypatch.setattr(telemetry, "_instrumentors", missing_instrumentors)
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", _StubExporter)
    monkeypatch.setattr(telemetry, "BatchSpanProcessor", _StubSpanProcessor)

    result = telemetry.setup_telemetry()

    assert result is trace.get_tracer_provider()
    assert telemetry._configured is True


@pytest.mark.unit
def test_instrumentor_set_covers_rq_sqlalchemy_sqlite3_httpx():
    import clerk.telemetry as telemetry

    names = [name for name, _ in telemetry._instrumentors()]
    assert names == ["rq", "sqlalchemy", "sqlite3", "httpx"]


@pytest.mark.unit
def test_traced_decorator_creates_span(monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry.trace, "get_tracer", lambda _name: provider.get_tracer("test"))

    @telemetry.traced("test.span")
    def do_work(value):
        return value + 1

    assert do_work(1) == 2

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "test.span"


@pytest.mark.unit
def test_traced_decorator_records_exception_and_reraises(monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.trace import StatusCode

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry.trace, "get_tracer", lambda _name: provider.get_tracer("test"))

    @telemetry.traced("test.fail")
    def boom():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        boom()

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "test.fail"
    assert spans[0].status.status_code == StatusCode.ERROR


@pytest.mark.unit
def test_traced_decorator_preserves_function_metadata():
    @telemetry.traced("test.meta")
    def documented():
        """Docstring."""

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "Docstring."


@pytest.mark.unit
def test_rearm_after_fork_swaps_stale_batch_processor(monkeypatch):
    """Stale BatchSpanProcessors are dropped, others kept, a fresh one added."""
    from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

    import clerk.telemetry as telemetry

    class FakeExporter(SpanExporter):
        def export(self, spans):
            return SpanExportResult.SUCCESS

        def shutdown(self):
            return SpanExportResult.SUCCESS

    provider = telemetry.build_provider(endpoint="http://test:10428/x")
    stale_batch = provider._active_span_processor._span_processors[1]  # the batch one

    monkeypatch.setattr(telemetry, "build_span_exporter", lambda endpoint=None: FakeExporter())
    unregister_calls = []
    monkeypatch.setattr(telemetry.atexit, "unregister", unregister_calls.append)

    telemetry._rearm_after_fork(provider)

    processors = provider._active_span_processor._span_processors
    assert stale_batch not in processors
    assert isinstance(processors[0], telemetry.BaggageSpanProcessor)
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    assert isinstance(processors[1], BatchSpanProcessor)
    assert len(processors) == 2
    assert unregister_calls == [stale_batch.shutdown]


@pytest.mark.unit
def test_setup_telemetry_registers_fork_handler(monkeypatch, no_global_side_effects):
    import clerk.telemetry as telemetry

    registered = {}
    monkeypatch.setattr(
        telemetry.os,
        "register_at_fork",
        lambda after_in_child=None: registered.update(handler=after_in_child),
    )
    monkeypatch.setattr(telemetry, "_configured", False)
    telemetry.setup_telemetry()
    assert registered["handler"] is telemetry._rearm_after_fork


@pytest.mark.skipif(not hasattr(__import__("os"), "fork"), reason="requires fork")
@pytest.mark.unit
def test_forked_child_exports_spans_after_fork(monkeypatch):
    """End-to-end proof: a span ended in a forked child reaches the exporter."""
    import os

    from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

    import clerk.telemetry as telemetry

    read_fd, write_fd = os.pipe()

    class PipeExporter(SpanExporter):
        def export(self, spans):
            os.write(write_fd, str(len(spans)).encode())
            return SpanExportResult.SUCCESS

        def shutdown(self):
            return SpanExportResult.SUCCESS

    monkeypatch.setattr(telemetry, "build_span_exporter", lambda endpoint=None: PipeExporter())
    provider = telemetry.build_provider(endpoint="http://test:10428/x")

    pid = os.fork()
    if pid == 0:
        # child: the fresh batch processor must export the span via
        # force_flush even though the inherited worker thread is gone
        try:
            telemetry._rearm_after_fork(provider)
            with provider.get_tracer("fork-test").start_as_current_span("child-span"):
                pass
            provider.force_flush()
        finally:
            os._exit(0)

    os.close(write_fd)
    data = os.read(read_fd, 64)
    os.waitpid(pid, 0)
    assert data == b"1"
