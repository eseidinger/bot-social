"""JSON stdout logging accepted by the Developer Platform workload collector."""

import json
import logging
import re
import sys

from opentelemetry import trace

MAX_MESSAGE_BYTES = 1800
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]+")


class PlatformJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = CONTROL_CHARACTERS.sub(" ", record.getMessage()).strip() or "Log message"
        encoded = message.encode("utf-8")[:MAX_MESSAGE_BYTES]
        message = encoded.decode("utf-8", errors="ignore")
        entry = {
            "level": record.levelname.lower(),
            "message": message,
            "logger": record.name,
        }
        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            entry["traceId"] = f"{context.trace_id:032x}"
            entry["spanId"] = f"{context.span_id:016x}"
        return json.dumps(entry, ensure_ascii=False, separators=(",", ":"))


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(PlatformJsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.captureWarnings(True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
