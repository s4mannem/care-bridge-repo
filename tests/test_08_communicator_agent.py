"""Unit and integration tests for Plan 08: Community Communications Agent."""

from __future__ import annotations

import asyncio
import json
import types
import unittest
from typing import Any, Dict

from carebridge.agents.communicator_agent import (
    COMMUNICATOR_AGENT_INSTRUCTION,
    build_community_communications_agent,
    communicator_after_model_guardrail,
    draft_bilingual_outreach_messages,
    format_outreach_messages_from_plan,
)
from carebridge.contracts.outreach_models import OutreachMessages
from carebridge.contracts.state_keys import (
    STATE_AUDIT_REPORT,
    STATE_FINAL_PLAN,
    STATE_OUTREACH_MESSAGES,
)
from carebridge.mocks.fulton_fixtures import (
    build_mock_audit_report,
    build_mock_draft_plan,
)
from carebridge.security.race_blind_guard import PolicyViolationError
from carebridge.telemetry.otel import get_tracer


class TestCommunicatorAgentPlan08(unittest.TestCase):
    """Test suite certifying Plan 08: Community Communications Agent."""

    def setUp(self) -> None:
        get_tracer().clear()

    def test_01_prompt_contract_and_agent_configuration(self) -> None:
        """Verify prompt placeholders and LlmAgent wiring."""
        self.assertIn("{final_plan?}", COMMUNICATOR_AGENT_INSTRUCTION)
        self.assertIn("{audit_report?}", COMMUNICATOR_AGENT_INSTRUCTION)
        self.assertIn("PROVISIONAL", COMMUNICATOR_AGENT_INSTRUCTION.upper())
        self.assertIn("Health Service Area", COMMUNICATOR_AGENT_INSTRUCTION)

        agent = build_community_communications_agent()
        self.assertEqual(agent.name, "community_communications_agent")
        self.assertEqual(agent.output_key, STATE_OUTREACH_MESSAGES)
        self.assertEqual(agent.output_schema, OutreachMessages)

    def test_02_produces_bilingual_outreach_and_runner_up_explanations(self) -> None:
        """Verify 4 bilingual stop drafts, runner-up neighborhood explanations, and HSA notes."""
        final_plan = build_mock_draft_plan(county_fips="13121")
        audit_report = build_mock_audit_report()

        state: Dict[str, Any] = {
            STATE_FINAL_PLAN: final_plan.model_dump(),
            STATE_AUDIT_REPORT: audit_report.model_dump(),
            "county_name": "Fulton",
        }
        tool_ctx = types.SimpleNamespace(state=state)

        payload = draft_bilingual_outreach_messages(
            county_fips="13121",
            tool_context=tool_ctx,
        )
        outreach = OutreachMessages.model_validate(payload)

        self.assertEqual(len(outreach.stop_notices), 4)
        for idx, notice in enumerate(outreach.stop_notices, start=1):
            self.assertEqual(notice.stop_rank, idx)
            self.assertTrue(notice.provisional_disclaimer_included)
            self.assertIn("proposed location", notice.english_notice.lower())
            self.assertIn("ubicación propuesta", notice.spanish_notice.lower())
            self.assertTrue(len(notice.why_chosen_explanation) > 30)

        # Verify Question 7 counterfactual explanations for unpicked neighborhoods
        self.assertEqual(len(outreach.unpicked_neighborhood_explanations), 2)
        for item in outreach.unpicked_neighborhood_explanations:
            self.assertTrue(item.tract_geoid.startswith("13121"))
            self.assertGreaterEqual(item.need_rank, 5)
            self.assertEqual(item.nearest_selected_stop_rank, 1)
            self.assertGreater(item.distance_to_selected_stop_km, 0.0)
            self.assertIn("stop #1", item.english_explanation.lower())
            self.assertIn("parada #1", item.spanish_explanation.lower())

        # Verify multi-county Health Service Area (HSA) mention in both languages
        self.assertIn("health service area", outreach.regional_surveillance_note_en.lower())
        self.assertIn("4-county", outreach.regional_surveillance_note_en.lower())
        self.assertIn("hsa", outreach.regional_surveillance_note_es.lower())
        self.assertIn("4 condados", outreach.regional_surveillance_note_es.lower())

        # Verify guardrail passes on valid OutreachMessages
        llm_resp = types.SimpleNamespace(text=outreach.model_dump_json())
        cb_ctx = types.SimpleNamespace(state=state)
        result = communicator_after_model_guardrail(cb_ctx, llm_resp)
        self.assertIsNone(result)

    def test_03_guardrail_rejects_confirmed_and_booked_claims(self) -> None:
        """Verify communicator_after_model_guardrail blocks 'confirmed and booked' claims."""
        final_plan = build_mock_draft_plan(county_fips="13121")
        outreach = format_outreach_messages_from_plan(final_plan)

        # Inject forbidden claim into Stop #1's English notice
        bad_payload = outreach.model_dump()
        bad_payload["stop_notices"][0]["english_notice"] = (
            "PROPOSED LOCATION: Adamsville-Collier Heights Library is confirmed and booked "
            "for Saturday with guaranteed appointments."
        )

        llm_resp = types.SimpleNamespace(text=json.dumps(bad_payload))
        cb_ctx = types.SimpleNamespace(state={})

        with self.assertRaises(PolicyViolationError) as ctx:
            communicator_after_model_guardrail(cb_ctx, llm_resp)
        self.assertIn("confirmed and booked", str(ctx.exception).lower())

    def test_04_guardrail_rejects_missing_provisional_disclaimer_or_hsa(self) -> None:
        """Verify guardrail rejects missing provisional disclaimers or missing HSA framing."""
        final_plan = build_mock_draft_plan(county_fips="13121")
        outreach = format_outreach_messages_from_plan(final_plan)

        # Case A: Missing provisional disclaimer in Spanish notice
        bad_provisional = outreach.model_dump()
        bad_provisional["stop_notices"][1]["spanish_notice"] = (
            "Clínica móvil disponible el sábado en South Fulton."
        )
        llm_resp_a = types.SimpleNamespace(text=json.dumps(bad_provisional))
        with self.assertRaises(PolicyViolationError) as ctx_a:
            communicator_after_model_guardrail(types.SimpleNamespace(state={}), llm_resp_a)
        self.assertIn("spanish notice is missing a provisional", str(ctx_a.exception).lower())

        # Case B: Missing multi-county HSA framing in regional surveillance note
        bad_hsa = outreach.model_dump()
        bad_hsa["regional_surveillance_note_en"] = (
            "County-level surveillance shows elevated flu activity in Fulton County."
        )
        llm_resp_b = types.SimpleNamespace(text=json.dumps(bad_hsa))
        with self.assertRaises(PolicyViolationError) as ctx_b:
            communicator_after_model_guardrail(types.SimpleNamespace(state={}), llm_resp_b)
        self.assertIn("health service area", str(ctx_b.exception).lower())

    def test_05_otel_span_and_in_memory_runner_execution(self) -> None:
        """Verify OpenTelemetry span attributes and end-to-end ADK InMemoryRunner execution."""
        from google.adk.runners import InMemoryRunner

        final_plan = build_mock_draft_plan(county_fips="13121")
        audit_report = build_mock_audit_report()
        agent = build_community_communications_agent()
        runner = InMemoryRunner(agent=agent, app_name="carebridge_test_08")

        initial_state: Dict[str, Any] = {
            STATE_FINAL_PLAN: final_plan.model_dump(),
            STATE_AUDIT_REPORT: audit_report.model_dump(),
            "county_fips": "13121",
        }
        session = runner.session_service.create_session_sync(
            app_name="carebridge_test_08",
            user_id="test-user",
            session_id="sess-plan-08",
            state=initial_state,
        )

        async def _run() -> None:
            async for _ in runner.run_async(
                user_id="test-user",
                session_id=session.id,
                new_message="Draft bilingual English/Spanish community outreach messages for Fulton County.",
            ):
                pass

        asyncio.run(_run())

        updated_session = runner.session_service.get_session_sync(
            app_name="carebridge_test_08",
            user_id="test-user",
            session_id=session.id,
        )
        self.assertIsNotNone(updated_session)
        assert updated_session is not None
        self.assertIn(STATE_OUTREACH_MESSAGES, updated_session.state)
        outreach = OutreachMessages.model_validate(updated_session.state[STATE_OUTREACH_MESSAGES])
        self.assertEqual(len(outreach.stop_notices), 4)
        self.assertEqual(len(outreach.unpicked_neighborhood_explanations), 2)

        # Verify OpenTelemetry span agent.communicator.draft_outreach
        spans = [
            s
            for s in get_tracer().recorded_spans
            if s.name == "agent.communicator.draft_outreach"
        ]
        self.assertGreaterEqual(len(spans), 1)
        latest_span = spans[-1]
        self.assertEqual(latest_span.attributes.get("stops_drafted_count"), 4)
        self.assertEqual(latest_span.attributes.get("languages"), ["en", "es"])


if __name__ == "__main__":
    unittest.main()
