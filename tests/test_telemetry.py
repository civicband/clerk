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
