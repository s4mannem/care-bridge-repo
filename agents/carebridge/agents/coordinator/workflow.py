"""ADK Coordinator workflow graph chaining ParallelAgent, Validator, LoopAgent, and Communicator."""

from __future__ import annotations

import copy
import sys
import time
import types as py_types
from typing import Any, Dict, Iterator, List, Optional, Set

from carebridge.agents.auditor_agent.agent import build_equity_rigor_auditor_agent
from carebridge.agents.communicator_agent.agent import build_community_communications_agent
from carebridge.agents.coordinator.exit_gate import (
    AuditLoopExitGate,
    BaseAgent,
    Event,
    EventActions,
)
from carebridge.agents.health_agent.agent import build_health_access_agent
from carebridge.agents.mobility_agent.agent import build_transit_community_agent
from carebridge.agents.planner_agent.agent import build_siting_planner_agent
from carebridge.agents.validator_agent.agent import build_evidence_validator_agent
from carebridge.security.race_blind_guard import PolicyViolationError
from carebridge.telemetry.otel import record_structured_log, trace_span


def _run_sub_agent_events(
    sub_agent: Any,
    state: Dict[str, Any],
    user_message: str = "",
) -> Iterator[Event]:
    """Executes either a `BaseAgent` (with `run_events`) or an `LlmAgent` (with `execute_with_state`)."""
    start_ns = time.time_ns()
    if hasattr(sub_agent, "run_events") and callable(getattr(sub_agent, "run_events")):
        for ev in sub_agent.run_events(state, user_message=user_message):
            yield ev
    else:
        payload = sub_agent.execute_with_state(state, user_message=user_message)
        escalate = bool(isinstance(payload, dict) and payload.get("escalate") is True)
        yield Event(
            author=getattr(sub_agent, "name", "agent"),
            actions=EventActions(escalate=escalate),
            payload=payload,
        )
    elapsed_ms = round((time.time_ns() - start_ns) / 1_000_000.0, 3)
    telemetry_plugin = state.get("_telemetry_plugin")
    if telemetry_plugin is not None and hasattr(telemetry_plugin, "record_agent_run"):
        telemetry_plugin.record_agent_run(
            agent_name=getattr(sub_agent, "name", "agent"),
            latency_ms=elapsed_ms,
            status="ok",
        )


class ParallelAgent(BaseAgent):
    """ADK-compatible `ParallelAgent` executing branches with isolated output keys."""

    def __init__(
        self,
        *,
        name: str,
        description: str = "",
        sub_agents: Optional[List[Any]] = None,
    ) -> None:
        super().__init__(name=name, description=description, sub_agents=sub_agents)
        output_keys: List[str] = [
            str(getattr(ag, "output_key"))
            for ag in self.sub_agents
            if getattr(ag, "output_key", None)
        ]
        if len(output_keys) != len(set(output_keys)):
            raise ValueError(
                f"ParallelAgent '{name}' sub-agents must have distinct output_keys; got {output_keys}."
            )

    def run_events(
        self,
        state: Dict[str, Any],
        user_message: str = "",
    ) -> Iterator[Event]:
        with trace_span(
            f"workflow.parallel.{self.name}",
            sub_agents=[getattr(a, "name", "") for a in self.sub_agents],
        ):
            baseline_snapshot = {
                k: copy.deepcopy(v) for k, v in state.items() if not k.startswith("_")
            }
            branch_deltas: List[Dict[str, Any]] = []
            written_keys: Set[str] = set()

            for branch_agent in self.sub_agents:
                branch_state: Dict[str, Any] = {
                    k: copy.deepcopy(v) for k, v in baseline_snapshot.items()
                }
                if "_telemetry_plugin" in state:
                    branch_state["_telemetry_plugin"] = state["_telemetry_plugin"]

                for ev in _run_sub_agent_events(branch_agent, branch_state, user_message=user_message):
                    yield ev

                delta: Dict[str, Any] = {}
                for k, v in branch_state.items():
                    if k.startswith("_"):
                        continue
                    if k not in baseline_snapshot or baseline_snapshot[k] != v:
                        if k in written_keys:
                            raise PolicyViolationError(
                                f"ParallelAgent '{self.name}' detected shared state write collision on key '{k}'."
                            )
                        written_keys.add(k)
                        delta[k] = v
                branch_deltas.append(delta)

            for delta in branch_deltas:
                state.update(delta)

            record_structured_log(
                component=self.name,
                event_type="parallel_fanout_complete",
                written_keys=sorted(written_keys),
            )


class LoopAgent(BaseAgent):
    """ADK-compatible `LoopAgent` supporting bounded iterations and `EventActions(escalate=True)`."""

    def __init__(
        self,
        *,
        name: str,
        description: str = "",
        max_iterations: int = 2,
        sub_agents: Optional[List[Any]] = None,
    ) -> None:
        super().__init__(name=name, description=description, sub_agents=sub_agents)
        self.max_iterations = max(1, int(max_iterations))

    def run_events(
        self,
        state: Dict[str, Any],
        user_message: str = "",
    ) -> Iterator[Event]:
        with trace_span(
            f"workflow.loop.{self.name}",
            max_iterations=self.max_iterations,
        ) as span:
            iterations_run = 0
            escalated = False

            for iteration in range(self.max_iterations):
                iterations_run = iteration + 1
                for sub_agent in self.sub_agents:
                    for ev in _run_sub_agent_events(sub_agent, state, user_message=user_message):
                        yield ev
                        if getattr(getattr(ev, "actions", None), "escalate", False):
                            escalated = True
                            break
                    if escalated:
                        break
                if escalated:
                    break

            span.set_attribute("iterations_run", iterations_run)
            span.set_attribute("escalated", escalated)
            record_structured_log(
                component=self.name,
                event_type="loop_complete",
                iterations_run=iterations_run,
                escalated=escalated,
            )


class SequentialAgent(BaseAgent):
    """ADK-compatible `SequentialAgent` chaining workflow stages deterministically."""

    def __init__(
        self,
        *,
        name: str,
        description: str = "",
        sub_agents: Optional[List[Any]] = None,
    ) -> None:
        super().__init__(name=name, description=description, sub_agents=sub_agents)

    def run_events(
        self,
        state: Dict[str, Any],
        user_message: str = "",
    ) -> Iterator[Event]:
        with trace_span(
            f"workflow.sequential.{self.name}",
            stages=[getattr(a, "name", "") for a in self.sub_agents],
        ):
            for stage_agent in self.sub_agents:
                for ev in _run_sub_agent_events(stage_agent, state, user_message=user_message):
                    yield ev


def _register_adk_workflow_agents() -> None:
    """Registers `ParallelAgent`, `LoopAgent`, and `SequentialAgent` on `google.adk.agents`."""
    google_pkg = sys.modules.setdefault("google", py_types.ModuleType("google"))
    adk_pkg = sys.modules.get("google.adk")
    if adk_pkg is None:
        adk_pkg = py_types.ModuleType("google.adk")
        sys.modules["google.adk"] = adk_pkg
        setattr(google_pkg, "adk", adk_pkg)

    adk_agents = sys.modules.get("google.adk.agents")
    if adk_agents is None:
        adk_agents = py_types.ModuleType("google.adk.agents")
        sys.modules["google.adk.agents"] = adk_agents
        setattr(adk_pkg, "agents", adk_agents)

    for cls_name, cls_obj in (
        ("BaseAgent", BaseAgent),
        ("ParallelAgent", ParallelAgent),
        ("LoopAgent", LoopAgent),
        ("SequentialAgent", SequentialAgent),
    ):
        if not hasattr(adk_agents, cls_name):
            setattr(adk_agents, cls_name, cls_obj)


_register_adk_workflow_agents()


def build_carebridge_coordinator_workflow() -> SequentialAgent:
    """Builds the 4-stage CareBridge AI Track 1 Coordinator ADK `SequentialAgent`."""
    evidence_parallel = ParallelAgent(
        name="evidence_collection_parallel",
        description="Lane 01 parallel fan-out: Health & Access Agent (A) + Transit & Community Agent (B).",
        sub_agents=[
            build_health_access_agent(),
            build_transit_community_agent(),
        ],
    )

    validator_gate = build_evidence_validator_agent()

    plan_audit_loop = LoopAgent(
        name="plan_audit_loop",
        description="Bounded Planner <-> Independent Auditor challenge loop (max 1 revision = 2 iterations).",
        max_iterations=2,
        sub_agents=[
            build_siting_planner_agent(),
            build_equity_rigor_auditor_agent(),
            AuditLoopExitGate(name="audit_loop_exit_gate"),
        ],
    )

    communicator = build_community_communications_agent()

    return SequentialAgent(
        name="carebridge_coordinator",
        description=(
            "CareBridge AI Track 1 Coordinator: Orchestrates parallel evidence gathering, "
            "4-resolution validation gate, race-blind planning, post-hoc equity auditing, "
            "and bilingual community outreach generation."
        ),
        sub_agents=[
            evidence_parallel,
            validator_gate,
            plan_audit_loop,
            communicator,
        ],
    )
