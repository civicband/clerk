"""Tests for telemetry setup."""

import pytest

from clerk import telemetry


@pytest.fixture(autouse=True)
def reset_configured(monkeypatch):
    monkeypatch.setattr(telemetry, "_configured", False)


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
def test_setup_telemetry_is_idempotent():
    first = telemetry.setup_telemetry()
    second = telemetry.setup_telemetry()
    assert first is second
    assert telemetry._configured is True


@pytest.mark.unit
def test_setup_telemetry_returns_provider_with_baggage_processor():
    from opentelemetry.processor.baggage import BaggageSpanProcessor
    from opentelemetry.sdk.trace import TracerProvider

    provider = telemetry.setup_telemetry()
    if not isinstance(provider, TracerProvider):
        pytest.skip("Global provider already set to non-SDK provider")
    processors = provider._active_span_processor._span_processors
    assert any(isinstance(p, BaggageSpanProcessor) for p in processors)
