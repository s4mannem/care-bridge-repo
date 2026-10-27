"""The agent's one tool: the Health & Access named queries, run over the BigQuery MCP server."""
import asyncio
from typing import Any

from ...contracts.api_models import PlanRequest
from ...contracts.evidence_models import HealthEvidence
from ...contracts.state_keys import STATE_HEALTH_EVIDENCE, STATE_PLAN_REQUEST
from ...data.bq_mcp import BigQueryMcp
from ...telemetry.otel import trace_span
from ...tools.evidence import build_health_evidence, health_evidence_queries

MCP_LINEAGE = "bigquery.googleapis.com/mcp:execute_sql_readonly"


async def collect_health_evidence(mcp: BigQueryMcp, county_fips: str, county_name: str,
                                  context: Any) -> HealthEvidence:
    q = health_evidence_queries(mcp.table)
    with trace_span("bq.mcp.health_evidence", county_fips=county_fips) as span:
        rows, counts, disease = await asyncio.gather(
            mcp.query(q["tracts"], {"fips": county_fips}, context),
            mcp.query(q["counts"], None, context),
            mcp.query(q["disease"], None, context))
        health = build_health_evidence(county_fips, county_name, rows, counts[0], disease[0])
        span.set_attribute("rows_returned", len(rows))
    return health.model_copy(update={"source_lineage": [*health.source_lineage, MCP_LINEAGE]})


def summarize(health: HealthEvidence) -> dict:
    """What the model sees: totals and caveats, not the 300+ tract rows."""
    rd = health.regional_disease
    gap = [t for t in health.tracts if t.km_to_safety_net is not None and t.km_to_safety_net > 3.0]
    return {
        "county": f"{health.county_name} ({health.county_fips})", "tracts": len(health.tracts),
        "tracts_over_3km_to_safety_net": len(gap), "care_sites": health.care_sites_count,
        "safety_net_sites": health.safety_net_sites_count, "shortage_areas": health.shortage_areas_count,
        "shortage_facilities": health.shortage_facilities_count, "max_hpsa_score": health.max_hpsa_score,
        "regional_disease": {"hsa": rd.hsa_name, "hsa_counties": rd.hsa_counties,
                             "latest_week_end": rd.latest_week_end, "data_unavailable": rd.data_unavailable},
        "missingness": health.missingness_flags, "transport": "Google-managed BigQuery MCP server",
    }


def make_fetch_county_health_evidence(mcp: BigQueryMcp):
    async def fetch_county_health_evidence(tool_context: Any) -> dict:
        """Fetch the county's tract health burden, safety-net distances, shortage designations and regional
        respiratory signal through the BigQuery MCP server.

        Reads the county from the plan request in session state, records the full HealthEvidence in
        `health_evidence`, and returns a short summary.
        """
        req = PlanRequest.model_validate(tool_context.state[STATE_PLAN_REQUEST])
        health = await collect_health_evidence(mcp, req.county_fips, req.county_name, tool_context)
        tool_context.state[STATE_HEALTH_EVIDENCE] = health.model_dump(mode="json")
        return summarize(health)

    return fetch_county_health_evidence
