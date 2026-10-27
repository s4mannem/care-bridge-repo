"""ADK Web / CLI root agent entrypoint (`adk web` / `adk run`)."""

from __future__ import annotations

from carebridge.agents.coordinator.workflow import build_carebridge_coordinator_workflow

root_agent = build_carebridge_coordinator_workflow()

__all__ = ["root_agent"]
