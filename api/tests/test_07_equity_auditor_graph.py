"""Plan 07 in the graph: the Gemini equity auditor's tools and the wrapper that settles its verdict.

The LLM is replaced by a scripted fake and the ACS query by a fixed comparison, so these run offline.
"""
import asyncio
from types import SimpleNamespace

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from carebridge.agents import graph
from carebridge.contracts.audit_models import AuditReport, DemographicImpactComparison
from carebridge.contracts.state_keys import (
    STATE_AUDIT_REPORT,
    STATE_DRAFT_PLAN,
    STATE_HEALTH_EVIDENCE,
    STATE_NON_DEMOGRAPHIC_FEEDBACK,
    STATE_REVISION_HISTORY,
    STATE_REVISION_REQUIRED,
)
from carebridge.mocks.fulton_fixtures import build_mock_draft_plan, build_mock_health_evidence
from carebridge.security.race_blind_guard import assert_race_blind_planner_input

CLAIM = "Bus riders reach Stop 1 in about 20 minutes on Saturday."
IMPACT = DemographicImpactComparison(
    county_total_pop=1_000_000, catchment_total_pop=120_000, county_svi_theme3_mean=0.6,
    catchment_svi_theme3_mean=0.4,
    group_comparisons={"Hispanic or Latino": {"county_pct": 8.0, "catchment_pct": 4.0, "parity_ratio": 0.5}},
    disparity_findings=["Hispanic or Latino: catchments reach 4.0% vs 8.0% county-wide (parity 0.50 < 0.80)."],
    requires_human_equity_review=True,
)


@pytest.fixture(autouse=True)
def fixed_impact(monkeypatch):
    monkeypatch.setattr(graph, "demographic_impact", lambda repo, draft, health: IMPACT)


def _state(revision: int = 0) -> dict:
    draft = build_mock_draft_plan().model_copy(update={"revision_number": revision})
    return {STATE_DRAFT_PLAN: draft.model_dump(mode="json"),
            STATE_HEALTH_EVIDENCE: build_mock_health_evidence().model_dump(mode="json"),
            STATE_REVISION_HISTORY: [draft.model_dump(mode="json")], "iteration_count": revision,
            "planner_summary": CLAIM}


def _tools(state: dict):
    rule, impact, flag = graph.build_auditor_tools(repo=None, max_revisions=1)
    ctx = SimpleNamespace(state=state)
    return (lambda: rule.func(tool_context=ctx), lambda: impact.func(tool_context=ctx),
            lambda **kw: flag.func(tool_context=ctx, **kw))


def _flag(**over) -> dict:
    return {"category": "unsupported_grain_claim", "affected_stop_ranks": [1], "quoted_claim": CLAIM,
            "description": "Distances are straight-line upper bounds; no transit feed is loaded.",
            "remediation_instruction": "Call it a straight-line distance, not a travel time.", **over}


def test_flag_requires_a_verbatim_quote():
    s = _state()
    *_, flag = _tools(s)
    assert not flag(**_flag(quoted_claim="Stop 1 has the fastest bus connection in the county"))["accepted"]
    assert flag(**_flag())["accepted"]
    assert s[graph.AUDITOR_ADDED_DEFECTS][0]["category"] == "unsupported_grain_claim"


def test_flag_refuses_demographic_content_and_rule_only_categories():
    s = _state()
    *_, flag = _tools(s)
    assert not flag(**_flag(remediation_instruction="Move a stop to raise Hispanic parity."))["accepted"]
    assert not flag(**_flag(category="catchment_overlap"))["accepted"]
    assert not s.get(graph.AUDITOR_ADDED_DEFECTS)


def test_rule_audit_returns_the_planners_claims_and_demographics_stay_in_their_tool():
    s = _state()
    rule, impact, _ = _tools(s)
    out = rule()
    assert out["planner_summary"] == CLAIM and len(out["stops"]) == len(build_mock_draft_plan().stops)
    assert "group_comparisons" not in out
    assert impact()["disparity_findings"] == IMPACT.disparity_findings


class ScriptedAuditor(BaseLlm):
    """Calls both audit tools, flags CLAIM, then writes its summary."""

    model: str = "scripted"

    async def generate_content_async(self, llm_request, stream=False):
        answered = {p.function_response.name for c in llm_request.contents for p in c.parts or []
                    if p.function_response}
        if "run_rule_audit" not in answered:
            parts = [types.Part(function_call=types.FunctionCall(name=n, args={}))
                     for n in ("run_rule_audit", "compare_demographic_impact")]
        elif "flag_evidentiary_defect" not in answered:
            parts = [types.Part(function_call=types.FunctionCall(name="flag_evidentiary_defect", args=_flag()))]
        else:
            parts = [types.Part(text="Rejected. The planner calls a straight-line distance a bus time. "
                                     "Hispanic or Latino residents are reached at parity 0.50.")]
        yield LlmResponse(content=types.Content(role="model", parts=parts))


def _run(state: dict, settings) -> tuple[dict, list[dict]]:
    llm = graph.build_auditor_llm(settings, repo=None)
    llm.model = ScriptedAuditor()
    auditor = graph.EquityRigorAuditor(name="equity_auditor", repo=None, max_revisions=1, sub_agents=[llm])

    async def go():
        sessions = InMemorySessionService()
        runner = Runner(app_name="t", agent=auditor, session_service=sessions)
        session = await sessions.create_session(app_name="t", user_id="u", state=state)
        ui = [e.custom_metadata[graph.UI_EVENT] async for e in runner.run_async(
            user_id="u", session_id=session.id, new_message=types.Content(role="user", parts=[types.Part(text="go")]))
            if e.custom_metadata and graph.UI_EVENT in e.custom_metadata]
        return (await sessions.get_session(app_name="t", user_id="u", session_id=session.id)).state, ui

    return asyncio.run(go())


def test_llm_defect_rejects_draft_0_and_only_non_demographic_feedback_goes_back(settings):
    state, ui = _run(_state(0), settings)
    report = AuditReport.model_validate(state[STATE_AUDIT_REPORT])
    assert state[STATE_REVISION_REQUIRED] is True and report.verdict.value == "rejected_revision_required"
    assert report.auditor_summary.startswith("Rejected.")
    assert report.demographic_impact.disparity_findings == IMPACT.disparity_findings
    feedback = state[STATE_NON_DEMOGRAPHIC_FEEDBACK]
    assert any(d["category"] == "unsupported_grain_claim" for d in feedback)
    assert_race_blind_planner_input(feedback)
    assert "Hispanic" not in str(feedback)
    verdict = next(e for e in ui if e["kind"] == "verdict")
    assert verdict["verdict"] == "reject" and verdict["conflict_ranks"]


def test_defect_left_on_revision_1_goes_to_human_review_not_another_revision(settings):
    state, ui = _run(_state(1), settings)
    assert state[STATE_REVISION_REQUIRED] is False and state[STATE_NON_DEMOGRAPHIC_FEEDBACK] == []
    assert state[STATE_AUDIT_REPORT]["verdict"] == "needs_human_review"
    assert any(e["kind"] == "finding" and e["message"].startswith("PARITY") for e in ui)
