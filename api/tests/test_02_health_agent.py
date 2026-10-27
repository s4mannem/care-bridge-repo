"""Health & Access agent (plan 02) over the BigQuery MCP client, offline: a fake MCP stands in for the server."""
import asyncio
from collections.abc import AsyncGenerator
from types import SimpleNamespace

import pytest

pytest.importorskip("google.adk.tools.mcp_tool.mcp_toolset")

from google.adk.agents import BaseAgent  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from carebridge.agents.graph import UI_EVENT, HealthAccessAgent  # noqa: E402
from carebridge.agents.health_agent import make_fetch_county_health_evidence  # noqa: E402
from carebridge.contracts.api_models import PlanRequest  # noqa: E402
from carebridge.contracts.evidence_models import HealthEvidence  # noqa: E402
from carebridge.contracts.state_keys import STATE_HEALTH_EVIDENCE, STATE_PLAN_REQUEST  # noqa: E402
from carebridge.data.bq_mcp import BigQueryMcp, McpQueryError, decode_query_result  # noqa: E402
from carebridge.security.race_blind_guard import PolicyViolationError  # noqa: E402

TRACT = {"geo_id": "13121001100", "total_pop": 4000, "latitude": 33.78, "longitude": -84.38,
         "pct_uninsured": 14.2, "pct_uninsured_all_ages": 11.0, "pct_asthma": 10.1, "pct_copd": 6.0,
         "pct_diabetes": 12.0, "pct_high_bp": 35.0, "pct_checkup": 74.5, "pct_no_vehicle": 20.0,
         "pct_age_65_plus": 9.0, "pct_mobility_difficulty": 7.0, "pct_lack_transport": None,
         "km_to_any_care": 1.2, "km_to_safety_net": 4.5, "extra_km_if_uninsured": 3.3,
         "days_over_20": 2, "mean_pm": 9.1}
COUNTS = {"care_sites": 40, "safety_net": 30, "shortage_areas": 0, "shortage_facilities": 6, "max_hpsa": 18.0}
DISEASE = {"hsa": "Atlanta", "hsa_counties": "Fulton, DeKalb, Clayton, Gwinnett", "last_week": "2024-09-28",
           "latest": {"covid": 1.1, "flu": 0.4, "rsv": 0.2}}


class FakeMcp(BigQueryMcp):
    def __init__(self, settings):
        super().__init__(settings)
        self.calls: list[tuple[str, dict | None]] = []

    async def query(self, sql, params=None, context=None):
        self.calls.append((sql, params))
        if "burden_tracts" in sql:
            return [TRACT]
        return [COUNTS] if "care_sites" in sql else [DISEASE]


def test_decode_query_result_handles_types_structs_and_nulls():
    result = {"isError": False, "structuredContent": {
        "jobComplete": True,
        "schema": {"fields": [
            {"name": "geo_id", "type": "STRING"}, {"name": "n", "type": "INTEGER"},
            {"name": "x", "type": "FLOAT"}, {"name": "ok", "type": "BOOLEAN"}, {"name": "none", "type": "FLOAT"},
            {"name": "latest", "type": "RECORD", "fields": [{"name": "covid", "type": "FLOAT"}]},
            {"name": "tags", "type": "STRING", "mode": "REPEATED"}]},
        "rows": [{"f": [{"v": "13121001100"}, {"v": "4075"}, {"v": "77.6"}, {"v": "true"}, {"v": None},
                        {"v": {"f": [{"v": "1.5"}]}}, {"v": [{"v": "a"}, {"v": "b"}]}]}]}}
    assert decode_query_result(result) == [{"geo_id": "13121001100", "n": 4075, "x": 77.6, "ok": True,
                                            "none": None, "latest": {"covid": 1.5}, "tags": ["a", "b"]}]


def test_decode_query_result_raises_on_error_or_incomplete_job():
    with pytest.raises(McpQueryError, match="denied"):
        decode_query_result({"isError": True, "content": [{"type": "text", "text": "Permission denied"}]})
    with pytest.raises(McpQueryError, match="complete"):
        decode_query_result({"isError": False, "structuredContent": {"jobComplete": False}})


@pytest.mark.parametrize("fips", ["13121' OR '1'='1", "1312", "131210"])
def test_query_rejects_non_fips_parameter_before_calling_the_server(settings, fips):
    mcp = BigQueryMcp(settings)
    with pytest.raises(ValueError):
        asyncio.run(mcp.query("SELECT 1 WHERE @fips = ''", {"fips": fips}))
    assert mcp._toolset is None


def test_query_rejects_write_sql(settings):
    with pytest.raises(PolicyViolationError):
        asyncio.run(BigQueryMcp(settings).query("DELETE FROM t WHERE TRUE", None))


def test_tool_writes_health_evidence_and_returns_only_a_summary(settings):
    mcp = FakeMcp(settings)
    ctx = SimpleNamespace(state={STATE_PLAN_REQUEST: PlanRequest(county_fips="13121").model_dump(mode="json")})
    summary = asyncio.run(make_fetch_county_health_evidence(mcp)(ctx))
    health = HealthEvidence.model_validate(ctx.state[STATE_HEALTH_EVIDENCE])
    assert len(health.tracts) == 1 and health.tracts[0].pct_checkup_gap == 25.5
    assert health.shortage_facilities_count == 6 and health.regional_disease.percent_visits_covid == 1.1
    assert health.source_lineage[-1].startswith("bigquery.googleapis.com/mcp")
    assert summary["tracts"] == 1 and summary["tracts_over_3km_to_safety_net"] == 1
    assert "geo_id" not in str(summary)
    assert [p for _, p in mcp.calls] == [{"fips": "13121"}, None, None]


class _SilentModel(BaseAgent):
    """Stands in for the LlmAgent answering without calling its tool."""

    async def _run_async_impl(self, ctx) -> AsyncGenerator:
        return
        yield


def test_agent_falls_back_to_the_queries_and_keeps_ui_events(settings):
    async def run():
        agent = HealthAccessAgent(name="health_access", mcp=FakeMcp(settings),
                                  sub_agents=[_SilentModel(name="health_access_agent")])
        sessions = InMemorySessionService()
        runner = Runner(app_name="t", agent=agent, session_service=sessions)
        s = await sessions.create_session(app_name="t", user_id="u", state={
            STATE_PLAN_REQUEST: PlanRequest(county_fips="13121").model_dump(mode="json")})
        msg = types.Content(role="user", parts=[types.Part(text="go")])
        ui = [(e.custom_metadata or {}).get(UI_EVENT) async for e in
              runner.run_async(user_id="u", session_id=s.id, new_message=msg)]
        state = (await sessions.get_session(app_name="t", user_id="u", session_id=s.id)).state
        return [u for u in ui if u], state

    ui, state = asyncio.run(run())
    assert [u["kind"] for u in ui] == ["start", "state_write"]
    assert ui[-1]["state_key"] == STATE_HEALTH_EVIDENCE and all(u["agent"] == "health_access" for u in ui)
    assert len(HealthEvidence.model_validate(state[STATE_HEALTH_EVIDENCE]).tracts) == 1
