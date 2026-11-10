from decimal import Decimal
from types import SimpleNamespace

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai import Agent, InstrumentationSettings
from pydantic_ai.capabilities import Instrumentation
from pydantic_ai.models.test import TestModel

from bot_social import agents, telemetry
from bot_social.web_research import FetchedPage


@pytest.mark.parametrize("content_flag, expected", [(None, False), ("true", True)])
def test_tracing_instruments_agents_with_explicit_content_control(
    monkeypatch, content_flag, expected
):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://localhost:4318/v1/traces")
    if content_flag is None:
        monkeypatch.delenv("BOT_SOCIAL_TRACE_CONTENT", raising=False)
    else:
        monkeypatch.setenv("BOT_SOCIAL_TRACE_CONTENT", content_flag)
    configured = []
    providers = []
    monkeypatch.setattr(
        telemetry.Agent, "instrument_all", lambda settings: configured.append(settings)
    )
    monkeypatch.setattr(
        telemetry.trace, "set_tracer_provider", lambda provider: providers.append(provider)
    )

    telemetry.configure_tracing("bot-social-worker")

    assert len(configured) == 1
    assert configured[0].include_content is expected
    assert configured[0].include_binary_content is False
    assert configured[0].include_model_request_parameters is False
    assert providers[0].resource.attributes["service.name"] == "bot-social-worker"
    providers[0].shutdown()


def test_tracing_is_disabled_without_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    monkeypatch.setattr(
        telemetry.Agent,
        "instrument_all",
        lambda _: pytest.fail("Instrumentation should remain disabled"),
    )
    telemetry.configure_tracing("bot-social-worker")


def test_agent_span_records_model_usage_and_prompt_hash_without_content(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(agents.trace, "get_tracer", lambda _: provider.get_tracer("test"))
    monkeypatch.setenv("BOT_SOCIAL_MODEL", "openai:test-model")

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        def run_sync(self, prompt, **kwargs):
            return SimpleNamespace(
                output="done",
                usage=lambda: SimpleNamespace(
                    requests=2,
                    tool_calls=1,
                    input_tokens=100,
                    output_tokens=20,
                    cost=Decimal("0.0042"),
                ),
            )

    monkeypatch.setattr(agents, "Agent", FakeAgent)
    assert (
        agents._run("editorial", "Private instruction", {"claim": "Private claim"}, str) == "done"
    )
    span = exporter.get_finished_spans()[0]
    assert span.attributes["agent.model"] == "openai:test-model"
    assert len(span.attributes["agent.prompt.sha256"]) == 16
    assert span.attributes["agent.usage.input_tokens"] == 100
    assert span.attributes["agent.usage.output_tokens"] == 20
    assert span.attributes["agent.cost.usd"] == 0.0042
    assert "Private claim" not in str(span.attributes)
    assert "Private instruction" not in str(span.attributes)
    provider.shutdown()


def test_research_spans_record_source_domain_and_counts(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(agents.trace, "get_tracer", lambda _: provider.get_tracer("test"))
    page = FetchedPage("https://example.org/report", "Report", ("The motor stopped.",))
    monkeypatch.setattr(agents, "fetch_page", lambda _: page)
    monkeypatch.setattr(agents, "_run", lambda *args, **kwargs: None)

    agents.research("The motor runs forever.", page.url, None)

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert spans["research.sources"].attributes["research.fetch.count"] == 1
    assert spans["research.sources"].attributes["research.page_count"] == 1
    assert spans["research.sources"].attributes["research.passage_count"] == 1
    assert spans["research.fetch"].attributes["source.host"] == "example.org"
    assert "The motor stopped." not in str(spans["research.fetch"].attributes)
    provider.shutdown()


@pytest.mark.parametrize("include_content", [False, True])
def test_pydantic_model_spans_include_usage_and_control_prompt_content(include_content):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    agent = Agent(
        TestModel(),
        instructions="Private instruction",
        capabilities=[
            Instrumentation(
                settings=InstrumentationSettings(
                    tracer_provider=provider,
                    include_content=include_content,
                    include_binary_content=False,
                )
            )
        ],
    )

    agent.run_sync("Private prompt")

    spans = exporter.get_finished_spans()
    assert any(span.attributes.get("gen_ai.usage.input_tokens", 0) > 0 for span in spans)
    assert ("Private prompt" in str([span.attributes for span in spans])) is include_content
    provider.shutdown()
