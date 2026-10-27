"""ADK Telemetry Plugin capturing agent invocations, latency, token counts, and audit loop verdicts."""

from __future__ import annotations

from typing import Any, Dict, List
from carebridge.telemetry.otel import (
    get_current_request_id,
    get_tracer,
    record_structured_log,
    trace_span,
)


class CareBridgeTelemetryPlugin:
    """Captures per-agent latency, token usage, tool calls, and audit verdicts for CareBridge AI."""

    def __init__(self) -> None:
        self.agent_invocations: Dict[str, int] = {}
        self.agent_latency_ms: Dict[str, List[float]] = {}
        self.token_usage: Dict[str, Dict[str, int]] = {}
        self.audit_verdicts: Dict[str, int] = {}

    def record_agent_run(
        self,
        agent_name: str,
        latency_ms: float,
        prompt_tokens: int = 0,
        candidate_tokens: int = 0,
        status: str = "ok",
    ) -> None:
        with trace_span(
            f"adk.agent.{agent_name}",
            agent_name=agent_name,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            candidate_tokens=candidate_tokens,
            status=status,
        ):
            self.agent_invocations[agent_name] = self.agent_invocations.get(agent_name, 0) + 1
            self.agent_latency_ms.setdefault(agent_name, []).append(round(latency_ms, 3))
            usage = self.token_usage.setdefault(
                agent_name, {"prompt_token_count": 0, "candidates_token_count": 0, "total_tokens": 0}
            )
            usage["prompt_token_count"] += prompt_tokens
            usage["candidates_token_count"] += candidate_tokens
            usage["total_tokens"] += prompt_tokens + candidate_tokens
            record_structured_log(
                component="CareBridgeTelemetryPlugin",
                event_type="agent_invocation",
                agent_name=agent_name,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                candidate_tokens=candidate_tokens,
                status=status,
            )

    def record_audit_verdict(self, verdict: str, revision_number: int) -> None:
        with trace_span("adk.audit.verdict", verdict=verdict, revision_number=revision_number):
            self.audit_verdicts[verdict] = self.audit_verdicts.get(verdict, 0) + 1
            record_structured_log(
                component="CareBridgeTelemetryPlugin",
                event_type="audit_verdict",
                verdict=verdict,
                revision_number=revision_number,
            )

    def summary(self) -> Dict[str, Any]:
        total_tokens = sum(v["total_tokens"] for v in self.token_usage.values())
        total_invocations = sum(self.agent_invocations.values())
        return {
            "request_id": get_current_request_id(),
            "total_agent_invocations": total_invocations,
            "total_tokens": total_tokens,
            "agent_invocations": dict(self.agent_invocations),
            "token_usage": dict(self.token_usage),
            "audit_verdicts": dict(self.audit_verdicts),
            "recorded_spans_count": len(get_tracer().recorded_spans),
        }
