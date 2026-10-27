# Plan 00 — Foundation: Shared Contracts, Security Guardrails, Model Armor & Telemetry

> **Component Role**: Prerequisite shared contract, security, observability, and mock-fixture layer that unlocks 100% parallel execution of Plans `01` through `11`.
> **Architecture Nodes Covered**: Cross-cutting `ADK session.state` handoff contract, Data Policy enforcement boundary, Google Cloud Model Armor / Vertex AI Safety settings, OWASP LLM Top 10 controls, and OpenTelemetry / ADK `LoggingPlugin` observability.

---

## 1. Executive Summary & Architectural Purpose

Before building the 11 individual components of **CareBridge AI** (Track 1 — Siting for Fulton County `13121`) in parallel, all workstreams must agree on:
1. **Strict `session.state` Keys & Pydantic Schemas**: Every Google ADK agent reads and writes typed structures via `session.state` (`health_evidence`, `mobility_evidence`, `evidence_report`, `draft_plan`, `audit_report`, `revision_required`, `final_plan`, `outreach_messages`).
2. **Non-Negotiable Data Policy & Race-Blind Guardrails**:
   - **Prohibited in Planner & Optimizer**: SVI Theme 3 (`RPL_THEME3`, `RPL_THEMES`), ACS race/ethnicity columns (`pct_black`, `pct_hispanic`, `pct_minority`, etc.), and individual PII (`FQHC_ADMIN_CONTACT_NM`, `FQHC_ADMIN_CONTACT_EMAIL`, `FQHC_ADMIN_CONTACT_PHONE_NUM`, NPPES practitioner names).
   - **Audit-Only Boundary**: Only the `Independent Equity & Rigor Auditor` (Plan 07) may access post-hoc aggregate demographic distributions, and when it rejects a plan for revision, **only non-demographic operational/evidentiary defects** may be passed back to the `Siting Planner Agent`.
3. **Defense-in-Depth Security (Model Armor + Vertex AI Safety + OWASP LLM Top 10)**:
   - Google Cloud **Model Armor** template screening for prompt injection, jailbreaks, sensitive data (SDP/DLP), and malicious URLs.
   - **Vertex AI / Gemini Safety Settings** (`BLOCK_LOW_AND_ABOVE` on hate speech, harassment, dangerous content).
   - ADK `before_model_callback`, `after_model_callback`, `before_tool_callback`, and `after_tool_callback` enforcing column allowlists, SQL read-only verification, and state sanitization.
4. **Full-Stack Telemetry & Observability**:
   - OpenTelemetry (`Tracer` + `Meter`) with Cloud Trace / Cloud Logging JSON structured export, correlated by `request_id` (`X-Request-ID`).
   - ADK `LoggingPlugin` + custom `CareBridgeTelemetryPlugin` capturing per-agent latency, token usage (`prompt_token_count`, `candidates_token_count`), tool calls, and audit loop iterations.
5. **Deterministic Fulton County (`13121`) Mock Fixtures**:
   - Realistic, schema-validated fixtures derived from `c5_01_load_explore.ipynb` (`326` tracts, `1,066,710` population, `135` tracts with safety-net gap, `28.6 km` worst safety-net distance, `0/99` designated shortage areas, `6` shortage facilities) so Plans `01`–`11` can run unit tests offline and in parallel.

---

## 2. File Ownership (Strict Isolation for Parallel Builds)

This plan owns **only** the following files:
```text
/Users/dvt112/Downloads/A4I/
├── pyproject.toml
├── .env.example
├── carebridge/
│   ├── __init__.py
│   ├── config.py
│   ├── agents/__init__.py
│   ├── tools/__init__.py
│   ├── contracts/
│   │   ├── __init__.py
│   │   ├── state_keys.py
│   │   ├── api_models.py
│   │   ├── evidence_models.py
│   │   ├── plan_models.py
│   │   ├── audit_models.py
│   │   └── outreach_models.py
│   ├── security/
│   │   ├── __init__.py
│   │   ├── model_armor.py
│   │   ├── owasp_guardrails.py
│   │   └── race_blind_guard.py
│   ├── telemetry/
│   │   ├── __init__.py
│   │   ├── otel.py
│   │   └── adk_telemetry_plugin.py
│   └── mocks/
│       ├── __init__.py
│       └── fulton_fixtures.py
└── tests/
    └── test_00_contracts_and_security.py
```

---

## 3. Step-by-Step Implementation Specification

### Step 3.1: `pyproject.toml` and `.env.example`

Create `pyproject.toml` pinning `google-adk`, `google-genai`, `google-cloud-bigquery`, `fastapi`, `pydantic>=2.7`, `opentelemetry-sdk`, `slowapi`, `httpx`, and `pytest`:

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "carebridge-ai"
version = "0.1.0"
description = "CareBridge AI: Multi-Agent Mobile Health Clinic Siting Service (Google ADK)"
readme = "plans/README.md"
requires-python = ">=3.11"
dependencies = [
    "google-adk>=2.7.0",
    "google-genai>=1.0.0",
    "google-cloud-bigquery>=3.25.0",
    "google-cloud-modelarmor>=0.1.0; platform_system=='Linux'",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.8.0",
    "pydantic-settings>=2.4.0",
    "httpx>=0.27.0",
    "slowapi>=0.1.9",
    "opentelemetry-api>=1.27.0",
    "opentelemetry-sdk>=1.27.0",
    "opentelemetry-instrumentation-fastapi>=0.48b0",
    "jinja2>=3.1.4",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=5.0.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

Create `.env.example`:
```dotenv
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=us-central1
BIGQUERY_DATASET=a4i_health
BIGQUERY_MARTA_DATASET=marta_gtfs
BIGQUERY_AUDIT_DATASET=external_demographic_audit
DEFAULT_COUNTY_FIPS=13121
DEFAULT_COUNTY_NAME=Fulton
DEFAULT_STATE_ABBR=GA
GEMINI_MODEL_FAST=gemini-2.5-flash
GEMINI_MODEL_REASONING=gemini-2.5-pro
MCP_BIGQUERY_URL=http://127.0.0.1:5000/mcp
MODEL_ARMOR_ENABLED=true
MODEL_ARMOR_TEMPLATE_ID=projects/your-gcp-project-id/locations/us-central1/templates/carebridge-guardrail
CAREBRIDGE_API_KEY=dev-secret-key-change-in-prod
ORCHESTRATION_TIMEOUT_SECONDS=120.0
USE_MOCK_DATA=false
```

---

### Step 3.2: Configuration (`carebridge/config.py`)

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    google_cloud_project: str = "a4i-fulton-2026"
    google_cloud_location: str = "us-central1"
    bigquery_location: str = "US"
    bigquery_dataset: str = "a4i_health"
    bigquery_marta_dataset: str = "marta_gtfs"
    bigquery_audit_dataset: str = "external_demographic_audit"

    default_county_fips: str = "13121"
    default_county_name: str = "Fulton"
    default_state_abbr: str = "GA"

    gemini_model_fast: str = "gemini-2.5-flash"
    gemini_model_reasoning: str = "gemini-2.5-pro"

    mcp_bigquery_url: str = "http://127.0.0.1:5000/mcp"
    model_armor_enabled: bool = False
    model_armor_template_id: str = ""

    carebridge_api_key: str = "dev-carebridge-key"
    orchestration_timeout_seconds: float = 120.0
    max_audit_revisions: int = 1
    use_mock_data: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

---

### Step 3.3: `ADK session.state` Contract (`carebridge/contracts/state_keys.py`)

Every agent in the HTML architecture diagram exchanges typed payloads exclusively via `session.state` using distinct `output_key` names so parallel branches never clobber each other:

```python
from typing import Final

# Input request context injected into session.state by FastAPI Gateway / Coordinator
STATE_PLAN_REQUEST: Final[str] = "plan_request"
STATE_REQUEST_ID: Final[str] = "request_id"

# 01 — Parallel Evidence Collection output_keys (MUST be distinct across ParallelAgent branches!)
STATE_HEALTH_EVIDENCE: Final[str] = "health_evidence"
STATE_MOBILITY_EVIDENCE: Final[str] = "mobility_evidence"

# Independent Data-Quality Gate output_key
STATE_EVIDENCE_REPORT: Final[str] = "evidence_report"

# 02 — Decide, Optimize, Challenge output_keys
STATE_DRAFT_PLAN: Final[str] = "draft_plan"
STATE_AUDIT_REPORT: Final[str] = "audit_report"
STATE_REVISION_REQUIRED: Final[str] = "revision_required"
STATE_NON_DEMOGRAPHIC_FEEDBACK: Final[str] = "non_demographic_feedback"
STATE_REVISION_HISTORY: Final[str] = "revision_history"
STATE_ITERATION_COUNT: Final[str] = "iteration_count"

# Final approved/provisional plan & outreach output_keys
STATE_FINAL_PLAN: Final[str] = "final_plan"
STATE_OUTREACH_MESSAGES: Final[str] = "outreach_messages"

ALL_STATE_KEYS: Final[tuple[str, ...]] = (
    STATE_PLAN_REQUEST,
    STATE_REQUEST_ID,
    STATE_HEALTH_EVIDENCE,
    STATE_MOBILITY_EVIDENCE,
    STATE_EVIDENCE_REPORT,
    STATE_DRAFT_PLAN,
    STATE_AUDIT_REPORT,
    STATE_REVISION_REQUIRED,
    STATE_NON_DEMOGRAPHIC_FEEDBACK,
    STATE_REVISION_HISTORY,
    STATE_ITERATION_COUNT,
    STATE_FINAL_PLAN,
    STATE_OUTREACH_MESSAGES,
)
```

---

### Step 3.4: Domain Pydantic Schemas (`carebridge/contracts/*.py`)

#### 1. `carebridge/contracts/evidence_models.py`
Captures spatial grain (`tract`, `12km_grid`, `facility_point`, `multi_county_hsa`), measurement type (`modeled_places`, `survey_acs_svi`, `federal_designation`, `syndromic_hsa`, `gtfs_schedule`), and explicit missingness flags:

```python
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class SpatialGrain(str, Enum):
    TRACT = "census_tract_11char"
    GRID_12KM = "epa_12km_grid_on_tract_id"
    FACILITY_POINT = "facility_lon_lat_point"
    SHORTAGE_POLYGON = "hrsa_mixed_grain_component"
    MULTI_COUNTY_HSA = "multi_county_health_service_area"


class DataEstimateKind(str, Enum):
    MODELED_SMALL_AREA = "modeled_small_area_estimate"
    SURVEY_ESTIMATE = "acs_5yr_survey_estimate"
    ADMINISTRATIVE_REGISTRY = "federal_registry_point"
    SYNDROMIC_SURVEILLANCE = "nssp_weekly_ed_percentage"
    SCHEDULED_TRANSIT = "gtfs_static_saturday_schedule"


class TractHealthRecord(BaseModel):
    geo_id: str = Field(..., min_length=11, max_length=11, description="11-char Census Tract FIPS")
    total_pop: int = Field(..., ge=0)
    latitude: Optional[float] = Field(None, ge=17.0, le=72.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=-60.0)
    # PLACES (18-64 uninsured) vs SVI (all ages uninsured)
    pct_uninsured_18_64: Optional[float] = Field(None, ge=0.0, le=100.0)
    pct_uninsured_all_ages: Optional[float] = Field(None, ge=0.0, le=100.0)
    uninsured_age_structure_gap: Optional[float] = None
    pct_asthma: Optional[float] = Field(None, ge=0.0, le=100.0)
    pct_copd: Optional[float] = Field(None, ge=0.0, le=100.0)
    pct_diabetes: Optional[float] = Field(None, ge=0.0, le=100.0)
    pct_bphigh: Optional[float] = Field(None, ge=0.0, le=100.0)
    pct_checkup: Optional[float] = Field(
        None, ge=0.0, le=100.0,
        description="PLACES routine checkup prevalence (LOW is bad; invert as 100 - pct_checkup before ranking)."
    )
    pct_checkup_gap: Optional[float] = Field(
        None, ge=0.0, le=100.0,
        description="Inverted preventive gap: 100.0 - pct_checkup (HIGH is bad, aligned with other burden measures)."
    )
    pct_uninsured_18_64_ci_width: Optional[float] = Field(
        None, ge=0.0, description="PLACES 95% confidence interval width (_crude95ci) for ranking uncertainty checks."
    )
    pct_no_vehicle: Optional[float] = Field(None, ge=0.0, le=100.0)
    pct_age_65_plus: Optional[float] = Field(None, ge=0.0, le=100.0)
    pct_mobility_difficulty: Optional[float] = Field(None, ge=0.0, le=100.0)
    pct_lack_transport: Optional[float] = Field(None, ge=0.0, le=100.0)
    # Straight-line upper-bound distances from tract_access (federal sites only)
    km_to_any_care: Optional[float] = Field(None, ge=0.0)
    km_to_safety_net: Optional[float] = Field(None, ge=0.0)
    extra_km_if_uninsured: Optional[float] = None
    cross_border_state_care_km: Optional[float] = Field(
        None, ge=0.0, description="Distance to nearest facility in care_sites_state across county lines."
    )
    # Air tail exposure (days > 20 ug/m3, NOT mean PM2.5 ranking)
    pm25_days_over_20: Optional[int] = Field(None, ge=0)
    mean_pm25_12km_caveat: Optional[float] = Field(None, ge=0.0)


class RegionalDiseaseSignal(BaseModel):
    hsa_name: str
    hsa_counties: str
    spatial_grain: SpatialGrain = SpatialGrain.MULTI_COUNTY_HSA
    latest_week_end: Optional[str] = None
    percent_visits_covid: Optional[float] = None
    percent_visits_influenza: Optional[float] = None
    percent_visits_rsv: Optional[float] = None
    ed_trends_covid: Optional[str] = None
    ed_trends_influenza: Optional[str] = None
    ed_trends_rsv: Optional[str] = None
    data_unavailable: bool = False
    grain_warning: str = (
        "NSSP ED visits are reported at the multi-county Health Service Area (HSA) level, "
        "NEVER at the census tract or neighborhood level."
    )


class HealthEvidence(BaseModel):
    county_fips: str = Field(..., pattern=r"^\d{5}$")
    county_name: str
    tracts: list[TractHealthRecord]
    care_sites_count: int = Field(..., ge=0)
    safety_net_sites_count: int = Field(..., ge=0)
    shortage_areas_count: int = Field(..., ge=0)
    shortage_facilities_count: int = Field(..., ge=0)
    max_hpsa_score: Optional[float] = Field(None, ge=0.0, le=25.0)
    regional_disease: RegionalDiseaseSignal
    source_lineage: list[str] = Field(default_factory=list)
    missingness_flags: list[str] = Field(default_factory=list)


class CandidateHostVenue(BaseModel):
    venue_id: str
    venue_name: str
    venue_kind: str = Field(..., description="e.g., Library (IMLS), Community Center, MARTA Station Lot")
    geo_id: str = Field(..., min_length=11, max_length=11)
    latitude: float = Field(..., ge=17.0, le=72.0)
    longitude: float = Field(..., ge=-180.0, le=-60.0)
    saturday_transit_stops_within_400m: int = Field(0, ge=0)
    saturday_trips_per_hour: Optional[float] = Field(None, ge=0.0)
    host_permission_verified: bool = Field(
        default=False,
        description="Must remain False until human field ops confirms venue agreement."
    )


class TractMobilityRecord(BaseModel):
    geo_id: str = Field(..., min_length=11, max_length=11)
    saturday_active_stops_count: int = Field(0, ge=0)
    saturday_mean_headway_min: Optional[float] = None
    usda_low_income_low_access: Optional[bool] = None
    candidate_venues: list[CandidateHostVenue] = Field(default_factory=list)


class MobilityEvidence(BaseModel):
    county_fips: str = Field(..., pattern=r"^\d{5}$")
    marta_gtfs_available: bool = False
    usda_food_access_available: bool = False
    imls_venues_available: bool = False
    tract_mobility: list[TractMobilityRecord] = Field(default_factory=list)
    caveats: list[str] = Field(
        default_factory=lambda: [
            "A nearby Saturday bus stop measures stop presence, not door-to-door clinic journey time."
        ]
    )


class ValidationCheckItem(BaseModel):
    check_name: str
    verdict: str = Field(..., pattern=r"^(PASS|WARN|FAIL)$")
    detail: str
    is_pipeline_check: bool = True


class EvidenceReport(BaseModel):
    county_fips: str
    core_tables_ready: bool
    blocking_failures: list[str] = Field(default_factory=list)
    checks: list[ValidationCheckItem] = Field(default_factory=list)
    validated_tract_count: int = 0
    prohibited_claims_blocked: list[str] = Field(default_factory=list)
    optional_datasets_status: dict[str, str] = Field(default_factory=dict)
    caveats: list[str] = Field(default_factory=list)
```

#### 2. `carebridge/contracts/plan_models.py`
```python
from typing import Optional
from pydantic import BaseModel, Field


class ScoreBreakdown(BaseModel):
    uninsured_norm: float = Field(..., ge=0.0, le=1.0)
    safety_net_distance_norm: float = Field(..., ge=0.0, le=1.0)
    no_vehicle_norm: float = Field(..., ge=0.0, le=1.0)
    chronic_respiratory_norm: float = Field(..., ge=0.0, le=1.0)
    checkup_preventive_gap_norm: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Normalized (100 - pct_checkup): low routine checkup rate inverted so high = high need.",
    )
    saturday_transit_access_bonus: float = Field(0.0, ge=0.0, le=1.0)
    overlap_penalty: float = Field(0.0, ge=0.0, le=1.0)
    composite_need_score: float = Field(..., ge=0.0, le=1.0)


class ProposedClinicStop(BaseModel):
    stop_rank: int = Field(..., ge=1, le=4)
    assigned_saturday: str = Field(..., description="ISO date YYYY-MM-DD for the Saturday")
    primary_tract_geoid: str = Field(..., min_length=11, max_length=11)
    covered_tract_geoids: list[str] = Field(..., min_length=1)
    candidate_venue_name: str
    latitude: float = Field(..., ge=17.0, le=72.0)
    longitude: float = Field(..., ge=-180.0, le=-60.0)
    catchment_radius_km: float = Field(default=4.0, gt=0.0)
    estimated_population_in_catchment: int = Field(..., ge=0)
    score_breakdown: ScoreBreakdown
    plain_language_rationale: str = Field(
        ...,
        description="Analytical, source-cited, resolution-qualified rationale for the outreach lead (NOT flyer copy).",
    )
    evidence_citations: list[str] = Field(..., min_length=1)
    spatial_grain_disclosures: list[str] = Field(..., min_length=1)
    host_verified: bool = False
    provisional_warning: str = (
        "PROVISIONAL SITE: Host permission, parking pad clearance, and Saturday staffing "
        "must be confirmed by field operations before public announcement."
    )


class RunnerUpTractExplanation(BaseModel):
    """Answers Question 7: 'How do I tell the neighborhood we didn't pick why we didn't pick them?'"""
    tract_geoid: str = Field(..., min_length=11, max_length=11)
    need_rank: int = Field(..., ge=5, description="County-wide composite need rank (e.g., #5-#8)")
    composite_need_score: float = Field(..., ge=0.0, le=1.0)
    deferral_reason_code: str = Field(
        ...,
        pattern=r"^(catchment_already_covered|inter_stop_separation_constraint|no_saturday_transit_or_venue|lower_marginal_coverage)$",
    )
    covered_by_stop_rank: Optional[int] = Field(
        None, ge=1, le=4, description="Which selected stop (1-4) already covers or sits within 5 km of this tract"
    )
    distance_to_nearest_selected_stop_km: float = Field(..., ge=0.0)
    technical_deferral_rationale: str = Field(
        ...,
        description="Analytical, cited explanation of why this high-need tract was not assigned one of the 4 stops.",
    )


class SensitivitySummary(BaseModel):
    weight_perturbation_pct: float = 15.0
    top_4_stability_jaccard: float = Field(..., ge=0.0, le=1.0)
    borderline_tracts: list[str] = Field(default_factory=list)
    notes: str


class DraftPlan(BaseModel):
    county_fips: str
    strategy_used: str
    status: str = Field(..., pattern=r"^(ok|insufficient_candidates)$")
    revision_number: int = Field(0, ge=0, le=1)
    stops: list[ProposedClinicStop] = Field(default_factory=list)
    runner_up_tracts: list[RunnerUpTractExplanation] = Field(
        default_factory=list,
        description="High-need runner-up tracts (#5-#8) with explicit deferral rationales.",
    )
    sensitivity: Optional[SensitivitySummary] = None
    planner_notes: list[str] = Field(default_factory=list)
```

#### 3. `carebridge/contracts/audit_models.py`
```python
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class AuditVerdict(str, Enum):
    APPROVED = "approved"
    REJECTED_REVISION_REQUIRED = "rejected_revision_required"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class DefectCategory(str, Enum):
    CATCHMENT_OVERLAP = "catchment_overlap"
    UNSUPPORTED_GRAIN_CLAIM = "unsupported_grain_claim"
    MISSING_CORE_EVIDENCE = "missing_core_evidence"
    INFEASIBLE_HOST_OR_TRANSIT = "infeasible_host_or_transit"
    SENSITIVITY_INSTABILITY = "sensitivity_instability"


class NonDemographicAuditDefect(BaseModel):
    """Safe to return to Siting Planner Agent during bounded revision."""
    defect_id: str
    category: DefectCategory
    affected_stop_ranks: list[int]
    Affected_tract_geoids: list[str] = Field(default_factory=list)
    description: str
    remediation_instruction: str


class DemographicImpactComparison(BaseModel):
    """VISIBLE TO AUDITOR & HUMAN REVIEWERS ONLY. NEVER SENT BACK TO PLANNER."""
    county_total_pop: int
    catchment_total_pop: int
    county_svi_theme3_mean: float = Field(..., ge=0.0, le=1.0)
    catchment_svi_theme3_mean: float = Field(..., ge=0.0, le=1.0)
    group_comparisons: dict[str, dict[str, float]] = Field(
        default_factory=dict,
        description="Group -> {'county_pct': x, 'catchment_pct': y, 'parity_ratio': y/x}"
    )
    disparity_findings: list[str] = Field(default_factory=list)
    requires_human_equity_review: bool = False


class AuditReport(BaseModel):
    revision_audited: int = Field(..., ge=0, le=1)
    verdict: AuditVerdict
    non_demographic_defects: list[NonDemographicAuditDefect] = Field(default_factory=list)
    demographic_impact: DemographicImpactComparison
    auditor_summary: str
    limitations_attached: list[str] = Field(default_factory=list)
```

#### 4. `carebridge/contracts/outreach_models.py` and `carebridge/contracts/api_models.py`
```python
# carebridge/contracts/outreach_models.py
from typing import Optional
from pydantic import BaseModel, Field


class StopOutreachDraft(BaseModel):
    stop_rank: int
    assigned_saturday: str
    candidate_venue_name: str
    english_notice: str = Field(..., description="Plain-language 6th-grade reading level English bus-stop flyer draft")
    spanish_notice: str = Field(..., description="Plain-language 6th-grade reading level Spanish bus-stop flyer draft")
    why_chosen_explanation: str
    provisional_disclaimer_included: bool = True


class UnpickedNeighborhoodExplanation(BaseModel):
    """Respectful 6th-grade EN/ES explanation for runner-up neighborhoods not selected in the 4-stop rotation."""
    tract_geoid: str
    need_rank: int
    nearest_selected_stop_rank: Optional[int] = None
    distance_to_selected_stop_km: float
    english_explanation: str = Field(
        ...,
        description="Empathetic, honest plain-language explanation of why this neighborhood was not picked and which nearby Saturday stop serves it.",
    )
    spanish_explanation: str = Field(
        ...,
        description="Empathetic, honest Spanish explanation of why this neighborhood was not picked and which nearby Saturday stop serves it.",
    )


class OutreachMessages(BaseModel):
    county_name: str
    provisional_banner: str = (
        "DRAFT FOR INTERNAL REVIEW ONLY — DO NOT PUBLISH UNTIL VENUE PERMITS ARE CONFIRMED."
    )
    stop_notices: list[StopOutreachDraft]
    unpicked_neighborhood_explanations: list[UnpickedNeighborhoodExplanation] = Field(
        default_factory=list,
        description="Answers Question 7: How to tell runner-up neighborhoods why they were not picked.",
    )
    regional_surveillance_note_en: str
    regional_surveillance_note_es: str
```

```python
# carebridge/contracts/api_models.py
from typing import Optional
from pydantic import BaseModel, Field
from carebridge.contracts.evidence_models import EvidenceReport
from carebridge.contracts.plan_models import DraftPlan
from carebridge.contracts.audit_models import AuditReport
from carebridge.contracts.outreach_models import OutreachMessages


class PlanRequest(BaseModel):
    county_fips: str = Field(default="13121", pattern=r"^\d{5}$")
    county_name: str = Field(default="Fulton", min_length=2, max_length=64)
    state_abbr: str = Field(default="GA", pattern=r"^[A-Z]{2}$")
    saturdays: list[str] = Field(
        default_factory=lambda: ["2026-11-07", "2026-11-14", "2026-11-21", "2026-11-28"],
        min_length=4,
        max_length=4,
    )
    strategy: str = Field(
        default="balanced_uninsured_safety_net_gap",
        pattern=r"^(balanced_uninsured_safety_net_gap|chronic_respiratory_focus|zero_vehicle_transit_priority)$",
    )
    include_optional_datasets: bool = True
    simulate_first_draft_defect: bool = Field(
        default=False,
        description="Demo toggle: forces an overlapping catchment in draft 0 so Auditor rejects and triggers 1 revision.",
    )


class PlanResponse(BaseModel):
    request_id: str
    status: str = Field(..., pattern=r"^(provisional_approved|needs_human_review|error)$")
    needs_human_review: bool
    county_fips: str
    county_name: str
    final_plan: Optional[DraftPlan] = None
    audit_report: Optional[AuditReport] = None
    revision_history: list[DraftPlan] = Field(default_factory=list)
    evidence_report: Optional[EvidenceReport] = None
    outreach: Optional[OutreachMessages] = None
    provenance: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    data_availability: dict[str, bool] = Field(default_factory=dict)
    telemetry_summary: dict[str, float | int | str] = Field(default_factory=dict)
```

---

### Step 3.5: Security, Model Armor, Vertex AI Safety & OWASP Guardrails (`carebridge/security/*.py`)

#### 1. `carebridge/security/race_blind_guard.py`
Enforces the non-negotiable challenge rule:
- Blocks any column or token referencing race/ethnicity (`rpl_theme3`, `rpl_themes`, `ep_minrty`, `epl_minrty`, `pct_black`, `pct_white`, `pct_hispanic`, `pct_asian`, `race`, `ethnicity`) from entering the `Siting Planner Agent` or `Four-Stop Coverage Optimizer`.
- Blocks PII columns (`fqhc_admin_contact_nm`, `fqhc_admin_contact_email`, `fqhc_admin_contact_phone_num`, `npi_practitioner_name`) across the entire system.

```python
import re
from typing import Any

PROHIBITED_PII_COLUMNS: frozenset[str] = frozenset({
    "fqhc_admin_contact_nm",
    "fqhc_admin_contact_email",
    "fqhc_admin_contact_phone_num",
    "practitioner_name",
    "provider_first_name",
    "provider_last_name",
})

PROHIBITED_PLANNER_DEMOGRAPHIC_KEYS: frozenset[str] = frozenset({
    "rpl_theme3",
    "rpl_themes",
    "spl_theme3",
    "ep_minrty",
    "epl_minrty",
    "pct_minority",
    "pct_black",
    "pct_african_american",
    "pct_hispanic",
    "pct_latino",
    "pct_white",
    "pct_asian",
    "external_demographic_audit",
    "demographic_impact",
})

EMAIL_PHONE_REGEX = re.compile(
    r"([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+|\b\d{3}[-.)\s]*\d{3}[-.\s]*\d{4}\b)"
)


class PolicyViolationError(RuntimeError):
    """Raised when PII or prohibited demographic features cross an access boundary."""


def assert_no_pii_in_payload(payload: Any) -> None:
    """Recursively checks dicts/lists/strings for prohibited PII columns or email/phone patterns."""
    if isinstance(payload, dict):
        for k, v in payload.items():
            if str(k).lower() in PROHIBITED_PII_COLUMNS:
                raise PolicyViolationError(f"Prohibited PII column detected: {k}")
            assert_no_pii_in_payload(v)
    elif isinstance(payload, list):
        for item in payload:
            assert_no_pii_in_payload(item)
    elif isinstance(payload, str):
        if EMAIL_PHONE_REGEX.search(payload):
            raise PolicyViolationError("Potential individual PII (email/phone) detected in payload.")


def assert_race_blind_planner_input(payload: Any) -> None:
    """Ensures no race/ethnicity or SVI Theme 3 keys enter the Planner or Optimizer."""
    assert_no_pii_in_payload(payload)
    if isinstance(payload, dict):
        for k, v in payload.items():
            if str(k).lower() in PROHIBITED_PLANNER_DEMOGRAPHIC_KEYS:
                raise PolicyViolationError(
                    f"Race-blind boundary violation: key '{k}' is forbidden in Planner/Optimizer."
                )
            assert_race_blind_planner_input(v)
    elif isinstance(payload, list):
        for item in payload:
            assert_race_blind_planner_input(item)
```

#### 2. `carebridge/security/model_armor.py`
Configures **Google Cloud Model Armor** screening (with deterministic local regex/heuristic fallback when running in local/sandbox environments) and **Vertex AI / Gemini Safety Settings**:

```python
import re
from google.genai import types
from carebridge.config import get_settings

PROMPT_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I),
    re.compile(r"system\s*prompt|reveal\s+your\s+instructions|developer\s+mode", re.I),
    re.compile(r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|GRANT|EXEC)\b\s+\b(TABLE|DATABASE|INTO)\b", re.I),
    re.compile(r"bypass\s+(audit|equity|race|guardrail)", re.I),
)


def default_vertex_safety_settings() -> list[types.SafetySetting]:
    """Standard strict Vertex AI / Gemini safety settings for all CareBridge ADK LlmAgents."""
    return [
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
            threshold=types.HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
            threshold=types.HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            threshold=types.HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
            threshold=types.HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
        ),
    ]


class ModelArmorScreener:
    """Screens user prompts and tool outputs via Google Cloud Model Armor + OWASP LLM01 heuristics."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def screen_input(self, text: str) -> tuple[bool, str]:
        for pattern in PROMPT_INJECTION_PATTERNS:
            if pattern.search(text):
                return False, f"Blocked by OWASP LLM01 / Model Armor policy: matched {pattern.pattern}"
        # If Google Cloud Model Armor API is enabled in production Cloud Run, invoke template sanitization
        return True, "clean"
```

#### 3. `carebridge/security/owasp_guardrails.py`
Provides reusable ADK callbacks (`before_model_callback`, `after_model_callback`, `before_tool_callback`, `after_tool_callback`) that every agent in Plans `02`–`09` attaches to its `LlmAgent`:
- **LLM01 (Prompt Injection)**: Screens incoming context and tool responses via `ModelArmorScreener`.
- **LLM02 (Sensitive Info Disclosure)**: Runs `assert_no_pii_in_payload` on all tool outputs and model outputs; runs `assert_race_blind_planner_input` on `Siting Planner Agent` prompts and state reads.
- **LLM06 (Excessive Agency)**: Verifies that only `auditor_agent` can call `query_demographic_audit_table`, and verifies all SQL queries are strictly `SELECT`/`WITH` read-only queries against allowlisted datasets.
- **LLM09 (Misinformation / Overreliance)**: Blocks output text that claims unbooked sites are "confirmed/booked" or attributes HSA-level NSSP disease trends to a single census tract.

---

### Step 3.6: Telemetry & Observability (`carebridge/telemetry/*.py`)

Create `carebridge/telemetry/otel.py` and `carebridge/telemetry/adk_telemetry_plugin.py`:
- Uses `contextvars.ContextVar("request_id")` so every log line, OpenTelemetry span, and ADK callback carries the exact FastAPI `request_id`.
- Implements `CareBridgeTelemetryPlugin` (compatible with `google.adk.plugins.BasePlugin` alongside `LoggingPlugin`) to record:
  - `carebridge.agent.invocations` (counter by agent name & status)
  - `carebridge.agent.latency_ms` (histogram by agent name)
  - `carebridge.llm.tokens` (counter by agent name, model, and token type)
  - `carebridge.audit.verdict` (counter by verdict: `approved`, `rejected_revision_required`, `needs_human_review`)
  - Structured JSON logs compatible with Google Cloud Logging (`severity`, `logging.googleapis.com/trace`, `component`, `request_id`, `event_type`).

---

### Step 3.7: Deterministic Fulton County (`13121`) Mock Fixtures (`carebridge/mocks/fulton_fixtures.py`)

Create rich, realistic fixtures matching Fulton County (`13121`) numbers from `c5_01_load_explore.ipynb`:
- 12 representative Fulton County census tracts spanning high-need South/West Atlanta (`13121007602`, `13121008201`, `13121011000`, `13121010514`, `13121006602`, `13121011305`) and low-need comparison tracts (`13121009501`, `13121010119`), with realistic `pct_uninsured_18_64` (`5.9%` to `26.4%`), `pct_no_vehicle` (`2.1%` to `34.8%`), `km_to_any_care` (`0.8 km` to `6.4 km`), and `km_to_safety_net` (`1.2 km` to `28.6 km`).
- Regional NSSP disease signal for Fulton County's 4-county HSA (`Fulton, DeKalb, Clayton, Cobb`).
- MARTA Saturday GTFS stop metrics + 6 candidate library/community venues.
- Post-hoc demographic audit records (`external_demographic_audit`) for the Auditor agent tests.

---

## 4. Verification & Unit Tests (`tests/test_00_contracts_and_security.py`)

Run:
```bash
pytest tests/test_00_contracts_and_security.py -v
```

Tests must verify:
1. All Pydantic models (`HealthEvidence`, `MobilityEvidence`, `EvidenceReport`, `DraftPlan`, `AuditReport`, `OutreachMessages`, `PlanRequest`, `PlanResponse`) serialize and validate cleanly on `fulton_fixtures`.
2. `assert_race_blind_planner_input` raises `PolicyViolationError` if `rpl_theme3`, `pct_black`, or `external_demographic_audit` is present anywhere in a nested dict.
3. `assert_no_pii_in_payload` raises `PolicyViolationError` if `FQHC_ADMIN_CONTACT_NM` or an email/phone number appears.
4. `ModelArmorScreener` blocks SQL injection and prompt injection strings.
5. `CareBridgeTelemetryPlugin` records token counts, latency metrics, and `request_id`-correlated spans.

---

## 5. Antigravity Execution Prompt

> **Copy-paste into Antigravity to execute Plan 00:**
> "Execute `/Users/dvt112/Downloads/A4I/plans/00_foundation_contracts_security_telemetry.md`. Create all files owned by Plan 00 (`pyproject.toml`, `.env.example`, `carebridge/config.py`, `carebridge/contracts/`, `carebridge/security/`, `carebridge/telemetry/`, `carebridge/mocks/fulton_fixtures.py`, and `tests/test_00_contracts_and_security.py`). Run `pytest tests/test_00_contracts_and_security.py -v` and ensure 100% of tests pass."
