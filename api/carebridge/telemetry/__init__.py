"""OpenTelemetry and ADK telemetry plugin package for CareBridge AI."""

from __future__ import annotations

from carebridge.telemetry.adk_telemetry_plugin import CareBridgeTelemetryPlugin
from carebridge.telemetry.otel import (
    get_current_request_id,
    get_tracer,
    record_structured_log,
    set_current_request_id,
    trace_span,
)

__all__ = [
    "CareBridgeTelemetryPlugin",
    "get_current_request_id",
    "get_tracer",
    "record_structured_log",
    "set_current_request_id",
    "trace_span",
]
