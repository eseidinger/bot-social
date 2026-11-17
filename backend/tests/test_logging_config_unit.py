import json
import logging
import warnings
from io import StringIO

from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

from bot_social import api, logging_config
from bot_social.logging_config import PlatformJsonFormatter


def test_platform_json_formatter_emits_bounded_trace_linked_record():
    formatter = PlatformJsonFormatter()
    record = logging.LogRecord(
        "bot_social.worker", logging.INFO, "", 0, "é" * 1000 + "\n", (), None
    )
    parent = SpanContext(trace_id=1, span_id=2, is_remote=False, trace_flags=TraceFlags(1))

    with trace.use_span(NonRecordingSpan(parent)):
        line = formatter.format(record)

    assert len(line.encode("utf-8")) < 4096
    parsed = json.loads(line)
    assert parsed["level"] == "info"
    assert parsed["logger"] == "bot_social.worker"
    assert len(parsed["message"].encode("utf-8")) <= 1800
    assert "\n" not in parsed["message"]
    assert parsed["traceId"] == "00000000000000000000000000000001"
    assert parsed["spanId"] == "0000000000000002"


def test_request_log_uses_route_template_instead_of_concrete_path(caplog):
    app = FastAPI()
    app.middleware("http")(api.trace_request)

    @app.get("/probe/{secret}")
    def probe(secret: str):
        return {"ok": bool(secret)}

    with caplog.at_level(logging.INFO, logger="bot_social.api"):
        response = TestClient(app).get("/probe/private-token")

    assert response.status_code == 200
    assert "GET /probe/{secret} 200" in caplog.text
    assert "private-token" not in caplog.text


def test_platform_logging_sends_python_warnings_as_json(monkeypatch):
    output = StringIO()
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    monkeypatch.setattr(logging_config.sys, "stdout", output)
    try:
        logging_config.configure_logging()
        warnings.showwarning("Deprecated operation", DeprecationWarning, "example.py", 1)
    finally:
        logging.captureWarnings(False)
        root.handlers = original_handlers
        root.setLevel(original_level)

    entry = json.loads(output.getvalue().strip())
    assert entry["level"] == "warning"
    assert entry["logger"] == "py.warnings"
    assert "Deprecated operation" in entry["message"]
