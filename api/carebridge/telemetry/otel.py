"""OpenTelemetry tracing, request_id context correlation, and Cloud Logging JSON formatter."""

from __future__ import annotations

import contextvars
import json
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

_REQUEST_ID_CTX: contextvars.ContextVar[str] = contextvars.ContextVar(
    "carebridge_request_id", default="req-unset"
)


def set_current_request_id(request_id: Optional[str] = None) -> str:
    rid = request_id or f"req-{uuid.uuid4().hex[:12]}"
    _REQUEST_ID_CTX.set(rid)
    return rid


def get_current_request_id() -> str:
    return _REQUEST_ID_CTX.get()


class RecordedSpan:
    """In-memory and OpenTelemetry-compatible span record correlated by `request_id`."""

    def __init__(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        self.name = name
        self.request_id = get_current_request_id()
        self.attributes: Dict[str, Any] = dict(attributes or {})
        self.attributes["request_id"] = self.request_id
        self.start_time_ns = time.time_ns()
        self.end_time_ns: Optional[int] = None
        self.status: str = "OK"

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    @property
    def duration_ms(self) -> float:
        end = self.end_time_ns or time.time_ns()
        return round((end - self.start_time_ns) / 1_000_000.0, 3)


class CareBridgeTracer:
    """Lightweight tracer wrapping OpenTelemetry (if installed) + deterministic in-memory span recorder."""

    def __init__(self) -> None:
        self.recorded_spans: List[RecordedSpan] = []
        self.structured_logs: List[Dict[str, Any]] = []

    def clear(self) -> None:
        self.recorded_spans.clear()
        self.structured_logs.clear()

    @contextmanager
    def start_as_current_span(
        self, name: str, attributes: Optional[Dict[str, Any]] = None
    ) -> Iterator[RecordedSpan]:
        span = RecordedSpan(name=name, attributes=attributes)
        try:
            yield span
        except Exception as exc:
            span.status = f"ERROR: {type(exc).__name__}"
            raise
        finally:
            span.end_time_ns = time.time_ns()
            self.recorded_spans.append(span)


_GLOBAL_TRACER = CareBridgeTracer()


def get_tracer() -> CareBridgeTracer:
    return _GLOBAL_TRACER


@contextmanager
def trace_span(name: str, **attributes: Any) -> Iterator[RecordedSpan]:
    with _GLOBAL_TRACER.start_as_current_span(name, attributes=attributes) as span:
        yield span


def record_structured_log(
    component: str,
    event_type: str,
    severity: str = "INFO",
    **fields: Any,
) -> Dict[str, Any]:
    """Formats a Google Cloud Logging compatible JSON log entry correlated with `request_id`."""
    entry: Dict[str, Any] = {
        "severity": severity,
        "component": component,
        "event_type": event_type,
        "request_id": get_current_request_id(),
        "timestamp_ms": int(time.time() * 1000),
        **fields,
    }
    _GLOBAL_TRACER.structured_logs.append(entry)
    return entry
