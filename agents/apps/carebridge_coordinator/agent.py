"""ADK app for `adk web` / `adk api_server`: the full CareBridge coordinator graph.

Send a PlanRequest as JSON (fields from `carebridge/contracts/api_models.py`),
e.g. {"strategy": "chronic_respiratory_focus", "simulate_first_draft_defect": true},
or any other text for the Fulton County defaults. One plan per session.
"""
from google.adk.agents import SequentialAgent

from adk_runtime.graph import build_adk_coordinator_workflow
from adk_runtime.intake import PlanFinalizer, PlanIntake

root_agent = SequentialAgent(
    name="carebridge",
    description="Plans four Saturday mobile clinic stops, audits them, and drafts EN/ES outreach.",
    sub_agents=[PlanIntake(name="plan_intake"), build_adk_coordinator_workflow(), PlanFinalizer(name="plan_finalizer")],
)
