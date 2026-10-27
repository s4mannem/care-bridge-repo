# Plan 01 — BigQuery Data Plane, SQL Views & MCP Toolset Boundary

> **Component Role**: Implements **Section 03 — BigQuery Data & Access Boundaries** from the CareBridge AI architecture diagram.
> **Architecture Nodes Covered**:
> - `BigQuery · a4i_health` (`burden_tracts`, `tract_access`, `care_sites`, `care_sites_state`, `shortage_areas`, `shortage_facilities`, `exposure_tracts`, `disease_weekly`)
> - `BigQuery · marta_gtfs & enrichments` (`v_tract_saturday_transit_access`, `external_food_access`, `candidate_venues`)
> - `Aggregate Demographic Reference` (`external_demographic_audit` — visible to Independent Auditor ONLY)
> - **Google-managed BigQuery MCP / MCP Toolbox** (`MCPToolset` with named, parameterized, read-only queries split into two strict permission boundaries: `evidence_mcp_toolset` and `audit_mcp_toolset`).

---

## 1. Executive Summary & Architectural Purpose

The HTML architecture states two non-negotiable rules for the data plane:
1. **"At least one Google-managed BigQuery MCP server is *actually consumed*."**
2. **"All queries are read-only · Google-managed BigQuery MCP / MCP Toolbox with named queries. DATA POLICY: Planner: structural factors only. Auditor: separate post-hoc demographic lookup."**

To enable parallel development while satisfying both live BigQuery MCP execution and local/CI testing:
- We define the **SQL setup scripts** for the optional MARTA Saturday GTFS views (`v_tract_saturday_transit_access`), optional enrichment views (`external_food_access`, `candidate_venues`), and the protected demographic audit table (`external_demographic_audit`).
- We define the **Google GenAI Toolbox for Databases (`mcp_tools.yaml`)** configuration containing named, parameterized, read-only SQL queries.
- We build `carebridge/data_plane/bq_mcp_client.py` which exposes:
  - `get_health_evidence_mcp_tools()`: Exposes ONLY `a4i_health` named queries (`query_tract_burden_and_access`, `query_care_sites_summary`, `query_shortage_designations`, `query_regional_disease_weekly`, `query_air_exposure_tail`).
  - `get_mobility_evidence_mcp_tools()`: Exposes ONLY `marta_gtfs` and enrichment named queries (`query_saturday_transit_access`, `query_candidate_venues`, `query_food_access_enrichment`), with graceful degradation if optional views are absent.
  - `get_auditor_demographic_mcp_tools()`: Exposes ONLY `query_demographic_audit_tracts` against `external_demographic_audit` — **physically omitted from the Evidence and Planner agents' toolsets**.

---

## 2. File Ownership (Strict Isolation for Parallel Builds)

This plan owns **only** the following files:
```text
/Users/dvt112/Downloads/A4I/
├── carebridge/
│   └── data_plane/
│       ├── __init__.py
│       ├── sql/
│       │   ├── 01_marta_gtfs_views.sql
│       │   ├── 02_optional_enrichments.sql
│       │   └── 03_demographic_audit_table.sql
│       ├── mcp_tools.yaml
│       ├── bq_mcp_client.py
│       └── data_validator.py
└── tests/
    └── test_01_bigquery_mcp.py
```

---

## 3. Step-by-Step Implementation Specification

### Step 3.1: MARTA Saturday GTFS View (`carebridge/data_plane/sql/01_marta_gtfs_views.sql`)

Creates `v_tract_saturday_transit_access` by spatially joining census tract polygons (`bigquery-public-data.geo_us_boundaries.census_tracts_georgia`) with MARTA GTFS stops (`marta_gtfs.stops`, `marta_gtfs.stop_times`, `marta_gtfs.trips`, `marta_gtfs.calendar`) active on Saturdays (`saturday = 1`), computing:
- `saturday_active_stops_count`: Number of Saturday-served transit stops within 400 meters of the tract boundary.
- `saturday_trips_count`: Total Saturday trips serving those stops between `08:00:00` and `18:00:00`.
- `saturday_mean_headway_min`: Estimated headway in minutes.
- Explicit comment/column reminding downstream consumers: *"Stop proximity is NOT door-to-door clinic travel time."*

```sql
-- carebridge/data_plane/sql/01_marta_gtfs_views.sql
CREATE SCHEMA IF NOT EXISTS `${PROJECT_ID}.marta_gtfs` OPTIONS(location="US");

CREATE OR REPLACE VIEW `${PROJECT_ID}.marta_gtfs.v_tract_saturday_transit_access` AS
WITH saturday_services AS (
  SELECT DISTINCT service_id
  FROM `${PROJECT_ID}.marta_gtfs.calendar`
  WHERE saturday = 1
),
saturday_stop_trips AS (
  SELECT
    st.stop_id,
    COUNT(DISTINCT t.trip_id) AS saturday_daytime_trips
  FROM `${PROJECT_ID}.marta_gtfs.stop_times` st
  JOIN `${PROJECT_ID}.marta_gtfs.trips` t USING (trip_id)
  JOIN saturday_services ss USING (service_id)
  WHERE st.arrival_time BETWEEN '08:00:00' AND '18:00:00'
  GROUP BY st.stop_id
),
active_stops AS (
  SELECT
    s.stop_id,
    s.stop_name,
    ST_GEOGPOINT(SAFE_CAST(s.stop_lon AS FLOAT64), SAFE_CAST(s.stop_lat AS FLOAT64)) AS stop_pt,
    COALESCE(sst.saturday_daytime_trips, 0) AS saturday_daytime_trips
  FROM `${PROJECT_ID}.marta_gtfs.stops` s
  INNER JOIN saturday_stop_trips sst USING (stop_id)
  WHERE s.stop_lon IS NOT NULL AND s.stop_lat IS NOT NULL
),
fulton_tracts AS (
  SELECT
    geo_id,
    tract_geom
  FROM `bigquery-public-data.geo_us_boundaries.census_tracts_georgia`
  WHERE STARTS_WITH(geo_id, '13121')
)
SELECT
  ft.geo_id,
  COUNT(DISTINCT a.stop_id) AS saturday_active_stops_count,
  COALESCE(SUM(a.saturday_daytime_trips), 0) AS saturday_daytime_trips_total,
  CASE
    WHEN COUNT(DISTINCT a.stop_id) > 0 AND SUM(a.saturday_daytime_trips) > 0
    THEN ROUND(600.0 / GREATEST(AVG(a.saturday_daytime_trips), 1.0), 1)
    ELSE NULL
  END AS saturday_mean_headway_min,
  'GTFS_SATURDAY_STOP_PROXIMITY_NOT_JOURNEY_TIME' AS metric_caveat
FROM fulton_tracts ft
LEFT JOIN active_stops a
  ON ST_DWITHIN(ft.tract_geom, a.stop_pt, 400)
GROUP BY ft.geo_id;
```

---

### Step 3.2: Optional Enrichments (`carebridge/data_plane/sql/02_optional_enrichments.sql`)

Defines schemas and seed views for:
1. `${PROJECT_ID}.marta_gtfs.candidate_venues` (IMLS public libraries and community centers in Fulton County `13121`, with `host_permission_verified = FALSE` by default so the agent never invents confirmed bookings).
2. `${PROJECT_ID}.marta_gtfs.external_food_access` (USDA Food Access Research Atlas tract flags `usda_low_income_low_access`).

---

### Step 3.3: Protected Post-Hoc Demographic Audit Table (`carebridge/data_plane/sql/03_demographic_audit_table.sql`)

Creates `${PROJECT_ID}.external_demographic_audit.tract_demographics_audit` in a **separate BigQuery dataset (`external_demographic_audit`)** so Cloud IAM dataset-level ACLs can grant `roles/bigquery.dataViewer` only to the Auditor service account and deny it to the Planner:
- Pulls Census ACS 5-year tract aggregate population counts (`total_pop`, `pop_black`, `pop_hispanic`, `pop_white_non_hisp`, `pop_asian`, `pct_minority`, and SVI Theme 3 `rpl_theme3`) for post-hoc population-weighted equity comparison.

```sql
-- carebridge/data_plane/sql/03_demographic_audit_table.sql
CREATE SCHEMA IF NOT EXISTS `${PROJECT_ID}.external_demographic_audit` OPTIONS(location="US");

CREATE OR REPLACE TABLE `${PROJECT_ID}.external_demographic_audit.tract_demographics_audit` AS
SELECT
  LPAD(CAST(geo_id AS STRING), 11, '0') AS geo_id,
  SUBSTR(LPAD(CAST(geo_id AS STRING), 11, '0'), 1, 5) AS county_fips,
  SAFE_CAST(total_pop AS INT64) AS total_pop,
  ROUND(SAFE_DIVIDE(black_pop, NULLIF(total_pop, 0)) * 100, 2) AS pct_black,
  ROUND(SAFE_DIVIDE(hispanic_pop, NULLIF(total_pop, 0)) * 100, 2) AS pct_hispanic,
  ROUND(SAFE_DIVIDE(white_pop, NULLIF(total_pop, 0)) * 100, 2) AS pct_white,
  ROUND(SAFE_DIVIDE(asian_pop, NULLIF(total_pop, 0)) * 100, 2) AS pct_asian,
  ROUND(SAFE_DIVIDE(total_pop - white_pop, NULLIF(total_pop, 0)) * 100, 2) AS pct_minority,
  PERCENT_RANK() OVER (
    PARTITION BY SUBSTR(LPAD(CAST(geo_id AS STRING), 11, '0'), 1, 5)
    ORDER BY SAFE_DIVIDE(total_pop - white_pop, NULLIF(total_pop, 0))
  ) AS rpl_theme3_proxy
FROM `bigquery-public-data.census_bureau_acs.censustract_2020_5yr`
WHERE STARTS_WITH(LPAD(CAST(geo_id AS STRING), 11, '0'), '13121');
```

---

### Step 3.4: Google-Managed BigQuery MCP / GenAI Toolbox Config (`carebridge/data_plane/mcp_tools.yaml`)

Define named, parameterized SQL tools for the Google MCP Toolbox for Databases (`mcp-toolbox` / BigQuery MCP server), divided into two toolsets:
1. **`evidence_toolset`** (accessible to `Health & Access Agent` and `Transit & Community Agent`):
   - `mcp_query_tract_burden_and_access(county_fips: str)`
   - `mcp_query_care_sites_and_shortages(county_fips: str)`
   - `mcp_query_regional_disease_weekly(county_fips: str)`
   - `mcp_query_saturday_transit_and_venues(county_fips: str)`
2. **`audit_only_toolset`** (accessible ONLY to `Independent Equity & Rigor Auditor`):
   - `mcp_query_posthoc_demographic_audit(county_fips: str)`

---

### Step 3.5: ADK `MCPToolset` & Read-Only Parameterized Client (`carebridge/data_plane/bq_mcp_client.py`)

Implement `BigQueryMCPBridge`:
- Connects to the Google-managed BigQuery MCP server via `google.adk.tools.mcp_tool.MCPToolset` (using `SseServerParams` or `StdioServerParameters` when `MCP_BIGQUERY_URL` is configured).
- Provides parameterized read-only `google.cloud.bigquery.Client` execution with `bigquery.QueryJobConfig(query_parameters=[...], maximum_bytes_billed=100_000_000)` and automatic fallback to `carebridge.mocks.fulton_fixtures` when `USE_MOCK_DATA=true`.
- Enforces **OWASP LLM06 (Excessive Agency) & SQL Injection Prevention**:
  - Every `county_fips` argument is validated against `^\d{5}$` and passed via `bigquery.ScalarQueryParameter("county_fips", "STRING", county_fips)`.
  - Raw ad-hoc SQL from an LLM is **never** executed; only named queries registered in `mcp_tools.yaml` are callable.
  - Runs `assert_race_blind_planner_input()` on all rows returned by `evidence_toolset` queries to guarantee zero demographic leakage.

---

## 4. Security, Guardrails & Telemetry

- **Read-Only Query Enforcement**: `maximum_bytes_billed=100_000_000` (100 MB cap per query) prevents BigQuery cost amplification / DoS (OWASP LLM04).
- **Dataset-Level Access Boundary**: `get_evidence_toolset()` and `get_audit_toolset()` return disjoint tool lists; `before_tool_callback` rejects any call to `mcp_query_posthoc_demographic_audit` unless `tool_context.agent_name == "equity_rigor_auditor"`.
- **Telemetry**: Every BigQuery / MCP tool call creates an OpenTelemetry span `bq.mcp.<tool_name>` with attributes `county_fips`, `rows_returned`, `bytes_billed`, `spatial_grain`, and `fallback_used`.

---

## 5. Verification & Unit Tests (`tests/test_01_bigquery_mcp.py`)

Run:
```bash
pytest tests/test_01_bigquery_mcp.py -v
```
Tests must verify:
1. Named queries reject non-5-digit `county_fips` (e.g., `"13121' OR '1'='1"` raises `ValueError`).
2. `get_health_evidence_mcp_tools()` and `get_mobility_evidence_mcp_tools()` never include `mcp_query_posthoc_demographic_audit`.
3. Graceful degradation when `marta_gtfs.v_tract_saturday_transit_access` or `external_food_access` is missing (`NotFound` exception returns `MobilityEvidence(marta_gtfs_available=False)` with an explicit caveat rather than crashing).
4. All outputs from evidence queries pass `assert_race_blind_planner_input()` and `assert_no_pii_in_payload()`.

---

## 6. Antigravity Execution Prompt

> **Copy-paste into Antigravity to execute Plan 01:**
> "Execute `/Users/dvt112/Downloads/A4I/plans/01_bigquery_data_plane_and_mcp.md`. Create all files in `carebridge/data_plane/` and `tests/test_01_bigquery_mcp.py`. Ensure all SQL scripts, `mcp_tools.yaml`, `bq_mcp_client.py`, and `data_validator.py` adhere strictly to the contracts in `carebridge/contracts/`. Run `pytest tests/test_01_bigquery_mcp.py -v` and confirm all tests pass."
