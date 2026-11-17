"""Optional OTLP tracing with content disabled unless explicitly enabled."""

import os

from opentelemetry import trace
from pydantic_ai import Agent, InstrumentationSettings


def traces_endpoint() -> str | None:
    if endpoint := os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
        return endpoint
    if endpoint := os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        traces_url = endpoint.rstrip("/") + "/v1/traces"
        os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = traces_url
        return traces_url
    return None


def configure_tracing(service_name: str) -> None:
    endpoint = traces_endpoint()
    if not endpoint:
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    sample_rate = float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0"))
    provider = TracerProvider(
        resource=Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", service_name)}),
        sampler=ParentBased(TraceIdRatioBased(sample_rate)),
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    Agent.instrument_all(
        InstrumentationSettings(
            include_content=os.getenv("BOT_SOCIAL_TRACE_CONTENT", "false").lower() == "true",
            include_binary_content=False,
            include_model_request_parameters=False,
        )
    )
