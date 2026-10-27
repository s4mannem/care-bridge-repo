"""Plan 08: the communications writer's brief, guardrails, template fallback and graph node."""

import asyncio
import json
import unittest

from google.adk.agents import BaseAgent
from google.adk.events import Event
from google.adk.runners import InMemoryRunner
from google.genai import types

from carebridge.agents.communicator_agent import (
    COMMUNICATOR_INSTRUCTION,
    PROVISIONAL_EN,
    PROVISIONAL_ES,
    build_brief,
    build_communicator_agent,
    merge_outreach,
)
from carebridge.agents.graph import UI_EVENT, CommunicationsAgent
from carebridge.config import Settings
from carebridge.contracts.api_models import PlanRequest
from carebridge.contracts.outreach_models import OutreachMessages
from carebridge.contracts.state_keys import (
    STATE_FINAL_PLAN,
    STATE_HEALTH_EVIDENCE,
    STATE_OUTREACH_MESSAGES,
    STATE_PLAN_REQUEST,
)
from carebridge.mocks.fulton_fixtures import build_mock_draft_plan, build_mock_health_evidence
from carebridge.tools.audit import draft_outreach


def _good_draft(plan) -> dict:
    return {
        "stops": [{"stop_rank": s.stop_rank,
                   "english_notice": "Free health checks this Saturday! Come see us. No insurance needed.",
                   "spanish_notice": "¡Chequeos de salud gratis este sábado! Venga a vernos. No necesita seguro.",
                   "why_chosen_explanation": "Many people here live far from a free clinic."} for s in plan.stops],
        "unpicked": [{"tract_geoid": r.tract_geoid,
                      "english_explanation": "We could not stop in every area this month. Please join us nearby.",
                      "spanish_explanation": "No pudimos parar en todas las zonas este mes. Acompáñenos cerca."}
                     for r in plan.runner_up_tracts],
        "regional_note_en": "Flu and COVID updates cover the whole metro area, not your street.",
        "regional_note_es": "Los datos de gripe y COVID cubren toda el área, no su calle.",
    }


class TestPlan08Communicator(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = build_mock_draft_plan()
        self.health = build_mock_health_evidence()
        self.template = draft_outreach(self.plan, self.health, "Fulton")

    def test_brief_comes_from_final_plan_only(self) -> None:
        brief = build_brief(self.plan, self.health.regional_disease, "Fulton")
        text = json.dumps(brief).lower()
        for forbidden in ("audit", "demographic", "minority", "race", "composite_need_score", "need_rank"):
            self.assertNotIn(forbidden, text)
        self.assertEqual([s["stop_rank"] for s in brief["stops"]], [s.stop_rank for s in self.plan.stops])
        self.assertEqual(len(brief["unpicked"]), len(self.plan.runner_up_tracts))

    def test_agent_has_the_opposite_posture_of_the_planner(self) -> None:
        agent = build_communicator_agent(Settings())
        self.assertEqual(agent.include_contents, "none")
        for phrase in ("sixth-grade", "Never use statistics", "Nothing is booked yet"):
            self.assertIn(phrase, COMMUNICATOR_INSTRUCTION)

    def test_good_output_is_used_and_every_notice_says_unconfirmed(self) -> None:
        out, fallbacks = merge_outreach(json.dumps(_good_draft(self.plan)), self.template)
        self.assertEqual(fallbacks, [])
        OutreachMessages.model_validate(out.model_dump())
        for n in out.stop_notices:
            self.assertTrue(n.english_notice.endswith(PROVISIONAL_EN))
            self.assertTrue(n.spanish_notice.endswith(PROVISIONAL_ES))
            self.assertIn("Free health checks", n.english_notice)
        self.assertEqual(out.regional_surveillance_note_en, _good_draft(self.plan)["regional_note_en"])

    def test_booking_claims_and_statistics_fall_back_per_item(self) -> None:
        draft = _good_draft(self.plan)
        draft["stops"][0]["english_notice"] = "Your spot is booked and confirmed!"
        draft["stops"][1]["spanish_notice"] = "El 40% de sus vecinos no tiene seguro."
        out, fallbacks = merge_outreach(json.dumps(draft), self.template)
        self.assertEqual(fallbacks, ["stop 1", "stop 2"])
        self.assertEqual(out.stop_notices[0], self.template.stop_notices[0])
        self.assertIn("Free health checks", out.stop_notices[2].english_notice)

    def test_invalid_output_returns_the_template(self) -> None:
        for raw in (None, "", "not json", json.dumps({"stops": []})):
            out, fallbacks = merge_outreach(raw, self.template)
            self.assertEqual(out, self.template)
            self.assertTrue(fallbacks)

    def test_graph_node_writes_outreach_and_keeps_ui_events(self) -> None:
        payload = json.dumps(_good_draft(self.plan))

        class FakeWriter(BaseAgent):
            async def _run_async_impl(self, ctx):
                yield Event(author=self.name, invocation_id=ctx.invocation_id,
                            content=types.Content(role="model", parts=[types.Part(text=payload)]))

        node = CommunicationsAgent(name="communications", sub_agents=[FakeWriter(name="writer")])

        async def run():
            runner = InMemoryRunner(agent=node, app_name="t")
            session = await runner.session_service.create_session(app_name="t", user_id="u", state={
                STATE_PLAN_REQUEST: PlanRequest().model_dump(mode="json"),
                STATE_FINAL_PLAN: self.plan.model_dump(mode="json"),
                STATE_HEALTH_EVIDENCE: self.health.model_dump(mode="json")})
            ui = [e.custom_metadata[UI_EVENT] async for e in runner.run_async(
                user_id="u", session_id=session.id, new_message=types.Content(role="user", parts=[types.Part(text="go")]))
                  if e.custom_metadata and UI_EVENT in e.custom_metadata]
            state = (await runner.session_service.get_session(app_name="t", user_id="u", session_id=session.id)).state
            return ui, state

        ui, state = asyncio.run(run())
        self.assertEqual([u["kind"] for u in ui], ["start", "state_write"])
        out = OutreachMessages.model_validate(state[STATE_OUTREACH_MESSAGES])
        self.assertIn("Free health checks", out.stop_notices[0].english_notice)
        self.assertNotIn("temp:communications_brief", state)


if __name__ == "__main__":
    unittest.main()
