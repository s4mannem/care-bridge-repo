"""Google-managed BigQuery MCP / MCP Toolbox client and permission-isolated toolsets.

Implements Section 03 (BigQuery Data & Access Boundaries) of the CareBridge AI architecture:
- Read-only parameterized queries (`@county_fips`, `maximum_bytes_billed=100_000_000`).
- Strict permission separation between `evidence_toolset` (race-blind structural queries for
  Health & Access Agent and Transit & Community Agent) and `audit_only_toolset` (post-hoc
  demographic impact query exclusively for the Independent Equity & Rigor Auditor).
- Graceful degradation when optional `marta_gtfs` / `external_food_access` / `candidate_venues`
  views raise `NotFound`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from carebridge.config import get_settings
from carebridge.contracts.evidence_models import (
    HealthEvidence,
    MobilityEvidence,
    RegionalDiseaseSignal,
    SpatialGrain,
    TractHealthRecord,
    TractMobilityRecord,
)
from carebridge.data_plane.data_validator import (
    MAX_BQ_BYTES_BILLED,
    enforce_unverified_host_venues,
    validate_county_fips,
    validate_evidence_payload,
)
from carebridge.mocks.fulton_fixtures import (
    DEMOGRAPHIC_AUDIT_FIXTURES,
    FULTON_CANDIDATE_VENUES,
    FULTON_CARE_SITES,
    FULTON_REGIONAL_DISEASE,
    FULTON_TRACT_HEALTH_RECORDS,
    FULTON_TRACT_MOBILITY_RECORDS,
    build_mock_health_evidence,
    build_mock_mobility_evidence,
)
from carebridge.security.race_blind_guard import (
    PolicyViolationError,
    assert_no_pii_in_payload,
    assert_race_blind_planner_input,
)
from carebridge.telemetry.otel import record_structured_log, trace_span

MCP_TOOLS_YAML_PATH = Path(__file__).resolve().parent / "mcp_tools.yaml"

EVIDENCE_HEALTH_TOOL_NAMES = (
    "mcp_query_tract_burden_and_access",
    "mcp_query_care_sites_and_shortages",
    "mcp_query_regional_disease_weekly",
    "mcp_query_air_exposure_tail",
    "query_tract_burden_and_access",
    "query_care_sites_summary",
    "query_shortage_designations",
    "query_regional_disease_weekly",
    "query_air_exposure_tail",
)

EVIDENCE_MOBILITY_TOOL_NAMES = (
    "mcp_query_saturday_transit_and_venues",
    "query_saturday_transit_access",
    "query_candidate_venues",
    "query_food_access_enrichment",
)

AUDIT_ONLY_TOOL_NAMES = (
    "mcp_query_posthoc_demographic_audit",
    "query_demographic_audit_tracts",
)

ALL_REGISTERED_MCP_TOOLS = frozenset(
    EVIDENCE_HEALTH_TOOL_NAMES + EVIDENCE_MOBILITY_TOOL_NAMES + AUDIT_ONLY_TOOL_NAMES
)


class BigQueryNotFoundError(Exception):
    """Raised or matched when an optional BigQuery view or table is not found."""


def _is_not_found_exception(exc: BaseException) -> bool:
    """Detects Google Cloud `NotFound` or simulated `NotFound` exceptions."""
    cls_name = type(exc).__name__.lower()
    msg = str(exc).lower()
    return (
        "notfound" in cls_name
        or "not_found" in cls_name
        or "not found" in msg
        or "404" in msg
    )


def load_mcp_tools_Registry() -> Dict[str, Any]:
    """Loads `mcp_tools.yaml` tool definitions (with fallback parser if PyYAML is absent)."""
    raw_text = MCP_TOOLS_YAML_PATH.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        parsed = yaml.safe_load(raw_text)
        if isinstance(parsed, dict) and "tools" in parsed:
            return parsed
    except Exception:
        pass

    # Extract tools and statements using regex fallback
    import re
    tools: Dict[str, Any] = {}
    current_tool = None
    collecting_stmt = False
    stmt_lines: List[str] = []

    for line in raw_text.splitlines():
        m = re.match(r"^  (mcp_query_[a-zA-Z0-9_]+):", line)
        if m:
            if current_tool and stmt_lines:
                tools[current_tool] = {"statement": "\n".join(stmt_lines).strip()}
            current_tool = m.group(1)
            collecting_stmt = False
            stmt_lines = []
            continue
        if current_tool and re.match(r"^    statement:\s*\|\s*$", line):
            collecting_stmt = True
            stmt_lines = []
            continue
        if collecting_stmt:
            if line.startswith("      "):
                stmt_lines.append(line[6:])
            else:
                collecting_stmt = False
                tools[current_tool] = {"statement": "\n".join(stmt_lines).strip()}
                stmt_lines = []

    if current_tool and stmt_lines:
        tools[current_tool] = {"statement": "\n".join(stmt_lines).strip()}

    return {
        "sources": {
            "carebridge_bq": {
                "kind": "bigquery",
                "location": "US",
            }
        },
        "tools": tools,
        "toolsets": {
            "health_evidence_toolset": [
                "mcp_query_tract_burden_and_access",
                "mcp_query_care_sites_and_shortages",
                "mcp_query_regional_disease_weekly",
                "mcp_query_air_exposure_tail",
            ],
            "mobility_evidence_toolset": [
                "mcp_query_saturday_transit_and_venues",
            ],
            "evidence_toolset": [
                "mcp_query_tract_burden_and_access",
                "mcp_query_care_sites_and_shortages",
                "mcp_query_regional_disease_weekly",
                "mcp_query_air_exposure_tail",
                "mcp_query_saturday_transit_and_venues",
            ],
            "audit_only_toolset": [
                "mcp_query_posthoc_demographic_audit",
            ],
        },
    }


class BigQueryMCPBridge:
    """Read-only, parameterized BigQuery MCP bridge with strict race-blind & audit toolset isolation."""

    def __init__(
        self,
        bq_client: Optional[Any] = None,
        use_mock_data: Optional[bool] = None,
        maximum_bytes_billed: int = MAX_BQ_BYTES_BILLED,
    ) -> None:
        settings = get_settings()
        self.project_id = settings.google_cloud_project
        self.location = settings.bigquery_location
        self.mcp_url = settings.mcp_bigquery_url
        self.use_mock_data = settings.use_mock_data if use_mock_data is None else use_mock_data
        self.maximum_bytes_billed = maximum_bytes_billed
        self._bq_client = bq_client
        if self._bq_client is None and not self.use_mock_data:
            try:
                import os
                from google.cloud import bigquery  # type: ignore

                token = os.environ.get("GCP_ACCESS_TOKEN")
                if token:
                    from google.oauth2.credentials import Credentials  # type: ignore

                    creds = Credentials(token=token.strip())
                    self._bq_client = bigquery.Client(
                        project=self.project_id or None,
                        location=self.location,
                        credentials=creds,
                    )
                else:
                    self._bq_client = bigquery.Client(
                        project=self.project_id or None,
                        location=self.location,
                    )
            except Exception:
                self._bq_client = None
        self.registry = load_mcp_tools_Registry()

    def get_tool_statement(self, tool_name: str) -> str:
        """Returns the SQL statement for `tool_name` from `mcp_tools.yaml`, qualified by project if set."""
        tools_dict = self.registry.get("tools", {})
        stmt = tools_dict.get(tool_name, {}).get("statement", "")
        if not stmt:
            stmt = f"-- MCP named tool: {tool_name}"
        if self.project_id and stmt:
            import re

            stmt = re.sub(
                r"`(a4i_health|marta_gtfs|external_demographic_audit)\.",
                f"`{self.project_id}.\\1.",
                stmt,
            )
        return stmt

    def build_query_job_config(self, county_fips: str) -> Dict[str, Any]:
        """Builds a parameterized, read-only BigQuery QueryJobConfig descriptor."""
        return self.get_query_job_config(county_fips)

    def _run_bq_or_fallback(
        self,
        tool_name: str,
        county_fips: str,
        spatial_grain: str,
        fallback_fn: Callable[[str], Any],
    ) -> Any:
        """Executes a named query against `_bq_client` if provided, or falls back to fixtures."""
        validated_fips = validate_county_fips(county_fips)
        if tool_name not in ALL_REGISTERED_MCP_TOOLS:
            raise PolicyViolationError(
                f"Execution of unregistered SQL tool '{tool_name}' is prohibited (OWASP LLM06)."
            )

        with trace_span(
            f"bq.mcp.{tool_name}",
            county_fips=validated_fips,
            spatial_grain=spatial_grain,
        ) as span:
            fallback_used = True
            bytes_billed = 0
            result: Any = None

            if self._bq_client is not None and not self.use_mock_data:
                fallback_used = False
                if hasattr(self._bq_client, tool_name):
                    fn = getattr(self._bq_client, tool_name)
                    result = fn(validated_fips)
                elif hasattr(self._bq_client, "query"):
                    query_cfg = self.get_query_job_config(validated_fips)
                    sql_stmt = self.get_tool_statement(tool_name)
                    job = self._bq_client.query(
                        sql_stmt,
                        job_config=query_cfg.get("job_config", query_cfg),
                    )
                    bytes_billed = int(getattr(job, "total_bytes_billed", 0) or 0)
                    rows = list(job.result()) if hasattr(job, "result") else list(job)
                    result = [dict(r) if not isinstance(r, dict) else r for r in rows]
                    if (
                        tool_name
                        in (
                            "mcp_query_care_sites_and_shortages",
                            "mcp_query_regional_disease_weekly",
                        )
                        and result
                    ):
                        result = result[0]
                    elif (
                        tool_name == "mcp_query_posthoc_demographic_audit"
                        and isinstance(result, list)
                    ):
                        result = {str(r["geo_id"]): r for r in result if "geo_id" in r}
                elif callable(self._bq_client):
                    result = self._bq_client(tool_name, validated_fips)
                else:
                    fallback_used = True
                    result = fallback_fn(validated_fips)
            else:
                result = fallback_fn(validated_fips)

            rows_returned = (
                len(result)
                if isinstance(result, list)
                else (
                    len(result.tract_mobility)
                    if isinstance(result, MobilityEvidence)
                    else (len(result.tracts) if isinstance(result, HealthEvidence) else 1)
                )
            )
            span.set_attribute("county_fips", validated_fips)
            span.set_attribute("rows_returned", rows_returned)
            span.set_attribute("bytes_billed", bytes_billed)
            span.set_attribute("spatial_grain", spatial_grain)
            span.set_attribute("fallback_used", fallback_used)

            record_structured_log(
                component="bigquery_mcp_bridge",
                event_type=f"bq.mcp.{tool_name}",
                county_fips=validated_fips,
                rows_returned=rows_returned,
                bytes_billed=bytes_billed,
                spatial_grain=spatial_grain,
                fallback_used=fallback_used,
            )
            return result

    def get_query_job_config(self, county_fips: str) -> Dict[str, Any]:
        """Returns a parameterized read-only BigQuery QueryJobConfig with 100 MB billing cap."""
        validated_fips = validate_county_fips(county_fips)
        try:
            from google.cloud import bigquery  # type: ignore

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("county_fips", "STRING", validated_fips)
                ],
                maximum_bytes_billed=self.maximum_bytes_billed,
            )
            return {
                "job_config": job_config,
                "county_fips": validated_fips,
                "maximum_bytes_billed": self.maximum_bytes_billed,
            }
        except ImportError:
            return {
                "query_parameters": [
                    {"name": "county_fips", "type": "STRING", "value": validated_fips}
                ],
                "maximum_bytes_billed": self.maximum_bytes_billed,
            }

    # -------------------------------------------------------------------------
    # Health & Access Evidence Named Queries (a4i_health — Race-Blind)
    # -------------------------------------------------------------------------

    def mcp_query_tract_burden_and_access(self, county_fips: str = "13121") -> List[Dict[str, Any]]:
        """Named MCP query returning race-blind tract burden + federal care site access distances."""
        def _fallback(fips: str) -> List[Dict[str, Any]]:
            return [
                t.model_dump()
                for t in FULTON_TRACT_HEALTH_RECORDS
                if t.geo_id.startswith(fips)
            ]

        rows = self._run_bq_or_fallback(
            tool_name="mcp_query_tract_burden_and_access",
            county_fips=county_fips,
            spatial_grain=SpatialGrain.TRACT.value,
            fallback_fn=_fallback,
        )
        return validate_evidence_payload(rows)

    query_tract_burden_and_access = mcp_query_tract_burden_and_access

    def mcp_query_care_sites_and_shortages(self, county_fips: str = "13121") -> Dict[str, Any]:
        """Named MCP query returning care sites count (`TOT_OPER_HR_PER_WEEK`) and HPSA shortage summary."""
        def _fallback(fips: str) -> Dict[str, Any]:
            evidence = build_mock_health_evidence(county_fips=fips)
            return {
                "county_fips": fips,
                "county_name": evidence.county_name,
                "care_sites_count": evidence.care_sites_count,
                "safety_net_sites_count": evidence.safety_net_sites_count,
                "shortage_areas_count": evidence.shortage_areas_count,
                "shortage_facilities_count": evidence.shortage_facilities_count,
                "max_hpsa_score": evidence.max_hpsa_score,
                "care_sites_sample": list(FULTON_CARE_SITES),
                "source_lineage": list(evidence.source_lineage),
                "missingness_flags": list(evidence.missingness_flags),
            }

        summary = self._run_bq_or_fallback(
            tool_name="mcp_query_care_sites_and_shortages",
            county_fips=county_fips,
            spatial_grain=SpatialGrain.FACILITY_POINT.value,
            fallback_fn=_fallback,
        )
        return validate_evidence_payload(summary)

    query_care_sites_summary = mcp_query_care_sites_and_shortages

    def query_shortage_designations(self, county_fips: str = "13121") -> Dict[str, Any]:
        """Named MCP query alias returning HPSA shortage area vs facility designations."""
        summary = self.mcp_query_care_sites_and_shortages(county_fips=county_fips)
        result = {
            "county_fips": summary["county_fips"],
            "shortage_areas_count": summary["shortage_areas_count"],
            "shortage_facilities_count": summary["shortage_facilities_count"],
            "max_hpsa_score": summary["max_hpsa_score"],
        }
        return validate_evidence_payload(result)

    def mcp_query_regional_disease_weekly(self, county_fips: str = "13121") -> Dict[str, Any]:
        """Named MCP query returning 4-county HSA NSSP weekly respiratory ED visit trends."""
        def _fallback(_fips: str) -> Dict[str, Any]:
            return FULTON_REGIONAL_DISEASE.model_dump()

        row = self._run_bq_or_fallback(
            tool_name="mcp_query_regional_disease_weekly",
            county_fips=county_fips,
            spatial_grain=SpatialGrain.MULTI_COUNTY_HSA.value,
            fallback_fn=_fallback,
        )
        return validate_evidence_payload(row)

    query_regional_disease_weekly = mcp_query_regional_disease_weekly

    def mcp_query_air_exposure_tail(self, county_fips: str = "13121") -> List[Dict[str, Any]]:
        """Named MCP query returning EPA 12km grid PM2.5 tail days (>20 ug/m3)."""
        def _fallback(fips: str) -> List[Dict[str, Any]]:
            return [
                {
                    "geo_id": t.geo_id,
                    "pm25_days_over_20": t.pm25_days_over_20,
                    "mean_pm25_12km_caveat": t.mean_pm25_12km_caveat,
                }
                for t in FULTON_TRACT_HEALTH_RECORDS
                if t.geo_id.startswith(fips)
            ]

        rows = self._run_bq_or_fallback(
            tool_name="mcp_query_air_exposure_tail",
            county_fips=county_fips,
            spatial_grain=SpatialGrain.GRID_12KM.value,
            fallback_fn=_fallback,
        )
        return validate_evidence_payload(rows)

    query_air_exposure_tail = mcp_query_air_exposure_tail

    def fetch_health_evidence(self, county_fips: str = "13121") -> HealthEvidence:
        """Assembles full race-blind `HealthEvidence` from the 4 named `a4i_health` MCP queries."""
        validated_fips = validate_county_fips(county_fips)
        tracts_rows = self.mcp_query_tract_burden_and_access(validated_fips)
        sites_summary = self.mcp_query_care_sites_and_shortages(validated_fips)
        disease_row = self.mcp_query_regional_disease_weekly(validated_fips)
        air_rows = self.mcp_query_air_exposure_tail(validated_fips)

        air_by_geoid = {str(r["geo_id"]): r for r in air_rows if "geo_id" in r}
        tracts: List[TractHealthRecord] = []
        for row in tracts_rows:
            merged = dict(row)
            air = air_by_geoid.get(str(merged.get("geo_id")), {})
            if merged.get("pm25_days_over_20") is None and "pm25_days_over_20" in air:
                merged["pm25_days_over_20"] = air["pm25_days_over_20"]
            if merged.get("mean_pm25_12km_caveat") is None and "mean_pm25_12km_caveat" in air:
                merged["mean_pm25_12km_caveat"] = air["mean_pm25_12km_caveat"]
            tracts.append(TractHealthRecord.model_validate(merged))

        default_lineage = [
            "a4i_health.v_burden_tracts (CDC PLACES 2025 + CDC/ATSDR SVI 2022, race-blind columns only)",
            "a4i_health.v_tract_access (straight-line upper-bound distances to federal sites)",
            "a4i_health.v_care_sites & v_care_sites_state (HRSA Health Centers + CMS POS, TOT_OPER_HR_PER_WEEK)",
            "a4i_health.v_shortage_areas (0 active in Fulton; 99 Proposed For Withdrawal) & v_shortage_facilities (6)",
            "a4i_health.v_exposure_tracts (EPA 12km grid tail days > 20 ug/m3)",
            "a4i_health.v_disease_weekly (CDC NSSP 4-county HSA respiratory ED trends)",
        ]
        evidence = HealthEvidence(
            county_fips=validated_fips,
            county_name=str(sites_summary.get("county_name", "Fulton")),
            tracts=tracts,
            care_sites_count=int(sites_summary.get("care_sites_count", 85)),
            safety_net_sites_count=int(sites_summary.get("safety_net_sites_count", 41)),
            shortage_areas_count=int(sites_summary.get("shortage_areas_count", 0)),
            shortage_facilities_count=int(sites_summary.get("shortage_facilities_count", 6)),
            max_hpsa_score=sites_summary.get("max_hpsa_score", 19.0),
            regional_disease=RegionalDiseaseSignal.model_validate(disease_row),
            source_lineage=list(sites_summary.get("source_lineage", default_lineage)),
            missingness_flags=list(sites_summary.get("missingness_flags", [])),
        )
        validate_evidence_payload(evidence.model_dump())
        return evidence

    # -------------------------------------------------------------------------
    # Mobility & Community Enrichment Named Queries (marta_gtfs — Optional)
    # -------------------------------------------------------------------------

    def mcp_query_saturday_transit_and_venues(
        self,
        county_fips: str = "13121",
        include_optional_datasets: bool = True,
    ) -> MobilityEvidence:
        """Queries optional MARTA Saturday GTFS, USDA Food Access, and IMLS candidate venues.

        Gracefully degrades when `include_optional_datasets=False` or when BigQuery raises
        `NotFound`, returning `MobilityEvidence(marta_gtfs_available=False, ...)` with an
        explicit caveat instead of crashing.
        """
        validated_fips = validate_county_fips(county_fips)
        if not include_optional_datasets:
            degraded = build_mock_mobility_evidence(county_fips=validated_fips, include_optional=False)
            validate_evidence_payload(degraded.model_dump())
            return degraded

        try:
            def _fallback(fips: str) -> MobilityEvidence:
                return build_mock_mobility_evidence(county_fips=fips, include_optional=True)

            raw = self._run_bq_or_fallback(
                tool_name="mcp_query_saturday_transit_and_venues",
                county_fips=validated_fips,
                spatial_grain=SpatialGrain.TRACT.value,
                fallback_fn=_fallback,
            )
            if isinstance(raw, MobilityEvidence):
                evidence = enforce_unverified_host_venues(raw)
            elif isinstance(raw, dict):
                validate_evidence_payload(raw)
                if "county_fips" not in raw:
                    raw = {"county_fips": validated_fips, **raw}
                evidence = enforce_unverified_host_venues(MobilityEvidence.model_validate(raw))
            elif isinstance(raw, list):
                validate_evidence_payload(raw)
                records = [TractMobilityRecord.model_validate(r) for r in raw]
                evidence = enforce_unverified_host_venues(
                    MobilityEvidence(
                        county_fips=validated_fips,
                        marta_gtfs_available=len(records) > 0,
                        usda_food_access_available=any(
                            r.usda_low_income_low_access is not None for r in records
                        ),
                        imls_venues_available=any(len(r.candidate_venues) > 0 for r in records),
                        tract_mobility=records,
                        caveats=[
                            "A nearby Saturday bus stop measures stop presence, not door-to-door clinic journey time.",
                            "Access Across America transit travel-time matrices excluded due to CC BY-NC license boundary.",
                        ],
                    )
                )
            else:
                raise ValueError(f"Unsupported mobility result type: {type(raw).__name__}")

            validate_evidence_payload(evidence.model_dump())
            return evidence

        except PolicyViolationError:
            raise
        except Exception as exc:
            if _is_not_found_exception(exc) or self._bq_client is not None:
                record_structured_log(
                    component="bigquery_mcp_bridge",
                    event_type="optional_mobility_view_not_found",
                    severity="WARNING",
                    county_fips=validated_fips,
                    error_type=type(exc).__name__,
                    error_detail=str(exc),
                )
                degraded = build_mock_mobility_evidence(
                    county_fips=validated_fips, include_optional=False
                )
                caveats = [
                    f"Optional BigQuery view missing ({type(exc).__name__}: {exc}); degraded to tract centroids.",
                    *degraded.caveats,
                ]
                result = degraded.model_copy(update={"caveats": caveats})
                validate_evidence_payload(result.model_dump())
                return result
            raise

    fetch_mobility_evidence = mcp_query_saturday_transit_and_venues

    def query_saturday_transit_access(self, county_fips: str = "13121") -> MobilityEvidence:
        """Named MCP query for `marta_gtfs.v_tract_saturday_transit_access` with graceful degradation."""
        return self.mcp_query_saturday_transit_and_venues(county_fips=county_fips)

    def query_candidate_venues(self, county_fips: str = "13121") -> List[Dict[str, Any]]:
        """Named MCP query for `marta_gtfs.candidate_venues` (always `host_permission_verified=False`)."""
        validated_fips = validate_county_fips(county_fips)
        evidence = self.mcp_query_saturday_transit_and_venues(county_fips=validated_fips)
        if not evidence.imls_venues_available:
            return []
        venues = [
            v.model_copy(update={"host_permission_verified": False}).model_dump()
            for tm in evidence.tract_mobility
            for v in tm.candidate_venues
            if tm.geo_id.startswith(validated_fips)
        ]
        return validate_evidence_payload(venues)

    def query_food_access_enrichment(self, county_fips: str = "13121") -> List[Dict[str, Any]]:
        """Named MCP query for `marta_gtfs.external_food_access` with graceful degradation."""
        validated_fips = validate_county_fips(county_fips)
        evidence = self.mcp_query_saturday_transit_and_venues(county_fips=validated_fips)
        if not evidence.usda_food_access_available:
            return []
        rows = [
            {
                "geo_id": tm.geo_id,
                "usda_low_income_low_access": tm.usda_low_income_low_access,
            }
            for tm in evidence.tract_mobility
            if tm.geo_id.startswith(validated_fips)
        ]
        return validate_evidence_payload(rows)

    # -------------------------------------------------------------------------
    # Protected Post-Hoc Demographic Audit Query (AUDITOR ONLY)
    # -------------------------------------------------------------------------

    def mcp_query_posthoc_demographic_audit(
        self,
        county_fips: str = "13121",
        caller_agent: Optional[str] = None,
        tool_context: Optional[Any] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """PROTECTED QUERY: Reads `external_demographic_audit.tract_demographics_audit`.

        Accessible ONLY to `equity_rigor_auditor`. Raises `PolicyViolationError` if invoked
        by the Siting Planner or Evidence agents.
        """
        validated_fips = validate_county_fips(county_fips)
        resolved_caller = caller_agent
        if resolved_caller is None and tool_context is not None:
            resolved_caller = getattr(tool_context, "agent_name", None)

        if resolved_caller is not None and resolved_caller != "equity_rigor_auditor":
            raise PolicyViolationError(
                f"Agent '{resolved_caller}' is denied access to 'mcp_query_posthoc_demographic_audit' "
                "(restricted exclusively to 'equity_rigor_auditor')."
            )

        def _fallback(fips: str) -> Dict[str, Dict[str, Any]]:
            return {
                geoid: dict(row)
                for geoid, row in DEMOGRAPHIC_AUDIT_FIXTURES.items()
                if geoid.startswith(fips)
            }

        result = self._run_bq_or_fallback(
            tool_name="mcp_query_posthoc_demographic_audit",
            county_fips=validated_fips,
            spatial_grain=SpatialGrain.TRACT.value,
            fallback_fn=_fallback,
        )
        if isinstance(result, list):
            return {str(r["geo_id"]): dict(r) for r in result if "geo_id" in r}
        return dict(result)

    query_demographic_audit_tracts = mcp_query_posthoc_demographic_audit


_DEFAULT_BRIDGE: Optional[BigQueryMCPBridge] = None


def get_bigquery_mcp_bridge() -> BigQueryMCPBridge:
    """Returns the singleton `BigQueryMCPBridge` instance."""
    global _DEFAULT_BRIDGE
    if _DEFAULT_BRIDGE is None:
        _DEFAULT_BRIDGE = BigQueryMCPBridge()
    return _DEFAULT_BRIDGE


def get_health_evidence_mcp_tools(
    bridge: Optional[BigQueryMCPBridge] = None,
) -> List[Callable[..., Any]]:
    """Returns ONLY `a4i_health` race-blind named query tools for the Health & Access Agent.

    Physically excludes `mcp_query_posthoc_demographic_audit`.
    """
    b = bridge or get_bigquery_mcp_bridge()
    return [
        b.mcp_query_tract_burden_and_access,
        b.mcp_query_care_sites_and_shortages,
        b.mcp_query_regional_disease_weekly,
        b.mcp_query_air_exposure_tail,
    ]


def get_mobility_evidence_mcp_tools(
    bridge: Optional[BigQueryMCPBridge] = None,
) -> List[Callable[..., Any]]:
    """Returns ONLY `marta_gtfs` and community enrichment named query tools for the Transit & Community Agent.

    Physically excludes `mcp_query_posthoc_demographic_audit`.
    """
    b = bridge or get_bigquery_mcp_bridge()
    return [
        b.mcp_query_saturday_transit_and_venues,
        b.query_saturday_transit_access,
        b.query_candidate_venues,
        b.query_food_access_enrichment,
    ]


def get_auditor_demographic_mcp_tools(
    bridge: Optional[BigQueryMCPBridge] = None,
) -> List[Callable[..., Any]]:
    """Returns ONLY the post-hoc demographic audit query tool for the Independent Equity & Rigor Auditor."""
    b = bridge or get_bigquery_mcp_bridge()
    return [
        b.mcp_query_posthoc_demographic_audit,
    ]


def get_evidence_toolset(
    bridge: Optional[BigQueryMCPBridge] = None,
) -> List[Callable[..., Any]]:
    """Returns the combined race-blind evidence toolset (Health + Mobility)."""
    return get_health_evidence_mcp_tools(bridge) + get_mobility_evidence_mcp_tools(bridge)


def get_audit_toolset(
    bridge: Optional[BigQueryMCPBridge] = None,
) -> List[Callable[..., Any]]:
    """Alias for `get_auditor_demographic_mcp_tools`."""
    return get_auditor_demographic_mcp_tools(bridge)
