"""Deterministic loop exit and final-plan promotion gate for the CareBridge AI Coordinator."""

from __future__ import annotations

import copy
import sys
import types as py_types
from typing import Any, Dict, Iterator, List, Optional

from carebridge.contracts.audit_models import AuditReport, AuditVerdict
from carebridge.contracts.evidence_models import EvidenceReport
from carebridge.contracts.plan_models import DraftPlan
from carebridge.contracts.state_keys import (
    STATE_AUDIT_REPORT,
    STATE_DRAFT_PLAN,
    STATE_EVIDENCE_REPORT,
    STATE_FINAL_PLAN,
    STATE_ITERATION_COUNT,
    STATE_NON_DEMOGRAPHIC_FEEDBACK,
    STATE_REVISION_REQUIRED,
)
from carebridge.telemetry.otel import record_structured_log, trace_span


class EventActions:
    """ADK-compatible EventActions carrying `escalate` and `state_delta`."""

    def __init__(
        self,
        *,
        escalate: bool = False,
        state_delta: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.escalate = bool(escalate)
        self.state_delta: Dict[str, Any] = dict(state_delta or {})


class Event:
    """ADK-compatible Event yielded by agents during workflow execution."""

    def __init__(
        self,
        *,
        author: str,
        actions: Optional[EventActions] = None,
        content: Optional[Any] = None,
        payload: Optional[Any] = None,
    ) -> None:
        self.author = author
        self.actions = actions or EventActions(escalate=False)
        self.content = content
        self.payload = payload if payload is not None else content

    def is_final_response(self) -> bool:
        return True


class InvocationContext:
    """ADK-compatible InvocationContext wrapping a `session` with `state`."""

    def __init__(self, state: Dict[str, Any], session: Optional[Any] = None) -> None:
        if session is not None:
            self.session = session
        else:
            self.session = py_types.SimpleNamespace(state=state)

    @property
    def state(self) -> Dict[str, Any]:
        return self.session.state


class BaseAgent:
    """ADK-compatible BaseAgent base class for custom and composite workflow agents."""

    def __init__(
        self,
        *,
        name: str,
        description: str = "",
        sub_agents: Optional[List[Any]] = None,
    ) -> None:
        self.name = name
        self.description = description
        self.sub_agents: List[Any] = list(sub_agents or [])

    def run_events(
        self,
        state: Dict[str, Any],
        user_message: str = "",
    ) -> Iterator[Event]:
        """Yields ADK `Event` objects while mutating `state`."""
        result = self.execute_with_state(state, user_message=user_message)
        yield Event(author=self.name, payload=result)

    def execute_with_state(
        self,
        state: Dict[str, Any],
        user_message: str = "",
    ) -> Any:
        """Executes the agent against `state` and returns its last event payload."""
        last_payload: Any = None
        for event in self.run_events(state, user_message=user_message):
            last_payload = event.payload
        return last_payload

    async def _run_async_impl(self, ctx: Any):
        """Standard ADK async generator entrypoint (`ctx.session.state`)."""
        session = getattr(ctx, "session", None)
        state = getattr(session, "state", None) if session is not None else getattr(ctx, "state", {})
        if not isinstance(state, dict):
            state = {}
        for event in self.run_events(state):
            yield event


def _register_adk_events_and_base_agent() -> None:
    """Ensures `BaseAgent`, `Event`, and `EventActions` are exposed on `google.adk.*`."""
    # Import health_agent first so its ADK fallback registers LlmAgent, FunctionTool, InMemoryRunner, and InMemorySessionService
    try:
        import carebridge.agents.health_agent.agent  # noqa: F401
    except Exception:
        pass

    google_pkg = sys.modules.setdefault("google", py_types.ModuleType("google"))
    if not hasattr(google_pkg, "__path__"):
        google_pkg.__path__ = []  # type: ignore[attr-defined]

    adk_pkg = sys.modules.get("google.adk")
    if adk_pkg is None:
        adk_pkg = py_types.ModuleType("google.adk")
        sys.modules["google.adk"] = adk_pkg
        setattr(google_pkg, "adk", adk_pkg)
    if not hasattr(adk_pkg, "__path__"):
        adk_pkg.__path__ = []  # type: ignore[attr-defined]

    adk_agents = sys.modules.get("google.adk.agents")
    if adk_agents is None:
        adk_agents = py_types.ModuleType("google.adk.agents")
        sys.modules["google.adk.agents"] = adk_agents
        setattr(adk_pkg, "agents", adk_agents)

    adk_events = sys.modules.get("google.adk.events")
    if adk_events is None:
        adk_events = py_types.ModuleType("google.adk.events")
        sys.modules["google.adk.events"] = adk_events
        setattr(adk_pkg, "events", adk_events)

    if not hasattr(adk_agents, "BaseAgent"):
        setattr(adk_agents, "BaseAgent", BaseAgent)
    if not hasattr(adk_events, "Event"):
        setattr(adk_events, "Event", Event)
    if not hasattr(adk_events, "EventActions"):
        setattr(adk_events, "EventActions", EventActions)


_register_adk_events_and_base_agent()


def compute_needs_human_review(state: Dict[str, Any]) -> bool:
    """Computes top-level `needs_human_review` from `audit_report`, `draft_plan`, and `evidence_report`."""
    raw_ev = state.get(STATE_EVIDENCE_REPORT)
    if raw_ev is not None:
        ev = raw_ev if isinstance(raw_ev, EvidenceReport) else EvidenceReport.model_validate(raw_ev)
        if not ev.core_tables_ready:
            return True

    raw_plan = state.get(STATE_FINAL_PLAN) or state.get(STATE_DRAFT_PLAN)
    if raw_plan is not None:
        plan = raw_plan if isinstance(raw_plan, DraftPlan) else DraftPlan.model_validate(raw_plan)
        if plan.status != "ok" or len(plan.stops) < 4:
            return True
    else:
        return True

    raw_audit = state.get(STATE_AUDIT_REPORT)
    if raw_audit is not None:
        audit = raw_audit if isinstance(raw_audit, AuditReport) else AuditReport.model_validate(raw_audit)
        verdict_val = audit.verdict.value if isinstance(audit.verdict, AuditVerdict) else str(audit.verdict)
        if verdict_val == AuditVerdict.NEEDS_HUMAN_REVIEW.value:
            return True
        if audit.demographic_impact is not None and audit.demographic_impact.requires_human_equity_review:
            return True

    return False


class AuditLoopExitGate(BaseAgent):
    """Deterministic exit gate for `plan_audit_loop` (`max_iterations=2`).

    Inspects `session.state`:
    - If `not revision_required` or `revision_number >= 1` or `not core_tables_ready`:
      - Promotes `draft_plan` -> `final_plan`.
      - Computes top-level `needs_human_review`.
      - Yields `Event(author=self.name, actions=EventActions(escalate=True))` to terminate `LoopAgent`.
    - Otherwise (when `revision_required == True` on `revision_number == 0`):
      - Increments `current_revision_number = 1` and `iteration_count = 1`.
      - Yields `Event(author=self.name, actions=EventActions(escalate=False))` so `LoopAgent` runs Iteration 2.
    """

    def __init__(
        self,
        name: str = "audit_loop_exit_gate",
        description: str = (
            "Checks revision_required and revision_number; promotes draft_plan to final_plan "
            "and escalates out of LoopAgent when approved or max revision reached."
        ),
    ) -> None:
        super().__init__(name=name, description=description)

    def evaluate_state(self, state: Dict[str, Any]) -> Event:
        """Evaluates loop state, mutates `state`, and returns an ADK `Event` with `EventActions`."""
        revision_required = bool(state.get(STATE_REVISION_REQUIRED, False))

        raw_ev = state.get(STATE_EVIDENCE_REPORT)
        core_tables_ready = True
        if isinstance(raw_ev, EvidenceReport):
            core_tables_ready = raw_ev.core_tables_ready
        elif isinstance(raw_ev, dict) and "core_tables_ready" in raw_ev:
            core_tables_ready = bool(raw_ev["core_tables_ready"])

        raw_draft = state.get(STATE_DRAFT_PLAN)
        revision_number = int(state.get("current_revision_number", state.get(STATE_ITERATION_COUNT, 0)) or 0)
        if isinstance(raw_draft, DraftPlan):
            revision_number = max(revision_number, int(raw_draft.revision_number))
        elif isinstance(raw_draft, dict) and "revision_number" in raw_draft:
            revision_number = max(revision_number, int(raw_draft["revision_number"]))

        should_exit = (not revision_required) or (revision_number >= 1) or (not core_tables_ready)

        raw_audit = state.get(STATE_AUDIT_REPORT)
        telemetry_plugin = state.get("_telemetry_plugin")
        if raw_audit is not None and telemetry_plugin is not None and hasattr(telemetry_plugin, "record_audit_verdict"):
            raw_verdict = (
                raw_audit.verdict
                if isinstance(raw_audit, AuditReport)
                else (
                    raw_audit.get("verdict")
                    if isinstance(raw_audit, dict)
                    else getattr(raw_audit, "verdict", "approved")
                )
            )
            verdict_str = (
                raw_verdict.value
                if isinstance(raw_verdict, AuditVerdict)
                else str(raw_verdict)
            )
            telemetry_plugin.record_audit_verdict(verdict_str, revision_number)

        with trace_span(
            "agent.coordinator.exit_gate",
            revision_number=revision_number,
            revision_required=revision_required,
            core_tables_ready=core_tables_ready,
            escalate=should_exit,
        ) as span:
            raw_fb = state.get(STATE_NON_DEMOGRAPHIC_FEEDBACK)
            if isinstance(raw_fb, list):
                normalized_fb: List[str] = []
                for item in raw_fb:
                    if isinstance(item, dict):
                        cat = str(item.get("category", "defect")).upper()
                        did = str(item.get("defect_id", "DEFECT"))
                        desc = str(item.get("description", ""))
                        normalized_fb.append(
                            f"[{cat}] {did}: {desc} — Enforce >= 5.0 km inter-stop separation and <= 20% catchment overlap on revision_number=1."
                        )
                    else:
                        normalized_fb.append(str(item))
                state[STATE_NON_DEMOGRAPHIC_FEEDBACK] = normalized_fb

            if should_exit:
                if (
                    revision_number >= 1
                    and not state.get(STATE_NON_DEMOGRAPHIC_FEEDBACK)
                    and state.get("_prior_non_demographic_feedback")
                ):
                    state[STATE_NON_DEMOGRAPHIC_FEEDBACK] = list(
                        state["_prior_non_demographic_feedback"]
                    )
                if raw_draft is not None:
                    final_plan_dict = (
                        copy.deepcopy(raw_draft.model_dump())
                        if isinstance(raw_draft, DraftPlan)
                        else copy.deepcopy(raw_draft)
                    )
                    state[STATE_FINAL_PLAN] = final_plan_dict
                state[STATE_REVISION_REQUIRED] = False
                needs_review = compute_needs_human_review(state)
                state["needs_human_review"] = needs_review
                span.set_attribute("needs_human_review", needs_review)

                payload = {
                    "escalate": True,
                    "revision_number": revision_number,
                    "needs_human_review": needs_review,
                    "final_plan_promoted": raw_draft is not None,
                }
                record_structured_log(
                    component="audit_loop_exit_gate",
                    event_type="loop_exit_escalate",
                    revision_number=revision_number,
                    needs_human_review=needs_review,
                )
                return Event(
                    author=self.name,
                    actions=EventActions(escalate=True, state_delta={STATE_FINAL_PLAN: state.get(STATE_FINAL_PLAN)}),
                    payload=payload,
                )

            # Trigger Iteration 2 (Revision 1)
            if state.get(STATE_NON_DEMOGRAPHIC_FEEDBACK):
                state["_prior_non_demographic_feedback"] = list(
                    state[STATE_NON_DEMOGRAPHIC_FEEDBACK]
                )
            state["current_revision_number"] = 1
            state[STATE_ITERATION_COUNT] = 1
            span.set_attribute("needs_human_review", False)

            payload = {
                "escalate": False,
                "current_revision_number": 1,
                "reason": "auditor_requested_revision_on_draft_0",
            }
            record_structured_log(
                component="audit_loop_exit_gate",
                event_type="loop_continue_revision_1",
                revision_number=revision_number,
                next_revision_number=1,
            )
            return Event(
                author=self.name,
                actions=EventActions(
                    escalate=False,
                    state_delta={"current_revision_number": 1, STATE_ITERATION_COUNT: 1},
                ),
                payload=payload,
            )

    def run_events(
        self,
        state: Dict[str, Any],
        user_message: str = "",
    ) -> Iterator[Event]:
        yield self.evaluate_state(state)

    def execute_with_state(
        self,
        state: Dict[str, Any],
        user_message: str = "",
    ) -> Dict[str, Any]:
        event = self.evaluate_state(state)
        return event.payload if isinstance(event.payload, dict) else {"escalate": event.actions.escalate}


# Alias matching Plan 09 overview header
AuditLoopExitChecker = AuditLoopExitGate
