"""Optional OTLP tracing with content disabled unless explicitly enabled."""

import os

from opentelemetry import trace
from pydantic_ai import Agent, InstrumentationSettings


def configure_tracing(service_name: str) -> None:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if not endpoint:
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    Agent.instrument_all(
        InstrumentationSettings(
            include_content=os.getenv("BOT_SOCIAL_TRACE_CONTENT", "false").lower() == "true",
            include_binary_content=False,
            include_model_request_parameters=False,
        )
    )
