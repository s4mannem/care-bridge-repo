# `carebridge/data_plane/sql` — BigQuery SQL Views & Isolation Scripts

The [`carebridge/data_plane/sql/`](file:///Users/dvt112/Downloads/A4I/carebridge/data_plane/sql) directory contains the read-only BigQuery DDL scripts that construct the optional transit/community enrichment views and the physically isolated post-hoc demographic audit view.

---

## SQL Scripts Overview

### 1. [`01_marta_gtfs_views.sql`](file:///Users/dvt112/Downloads/A4I/carebridge/data_plane/sql/01_marta_gtfs_views.sql)
Creates `a4i-fulton-2026.marta_gtfs.v_tract_saturday_transit_access`:
- Filters `marta_gtfs.calendar` for active Saturday service (`WHERE saturday = 1`).
- Filters `marta_gtfs.stop_times` to Saturday clinic operating hours (`08:00:00` to `18:00:00`).
- Uses `ST_DWITHIN(t.tract_geom, ST_GEOGPOINT(s.stop_lon, s.stop_lat), 400)` to count Saturday transit stops within a 400 m walk buffer of each census tract (`saturday_active_stops_count`, `saturday_trip_events_count`).
- Attaches the mandatory analytical caveat column `transit_metric_caveat = 'GTFS_SATURDAY_STOP_PROXIMITY_NOT_JOURNEY_TIME'` so downstream agents never claim end-to-end travel times.

### 2. [`02_optional_enrichments.sql`](file:///Users/dvt112/Downloads/A4I/carebridge/data_plane/sql/02_optional_enrichments.sql)
Creates two race-blind community enrichment views in `a4i-fulton-2026.a4i_health`:
- **`v_tract_candidate_venues`**:
  - Maps IMLS public libraries and community centers to their containing 11-character `geo_id`.
  - Explicitly hardcodes `FALSE AS host_permission_verified` and `'UNVERIFIED_CANDIDATE_HOST_REQUIRES_OUTREACH' AS venue_status_caveat`.
- **`v_tract_food_access_enrichment`**:
  - Extracts `low_income_low_access_1mi_flag` (`LILATracts_1And10`) and `pct_low_access_pop_1mi` (`lapop1share`) as a proxy for neighborhood resource co-location.

### 3. [`03_demographic_audit_table.sql`](file:///Users/dvt112/Downloads/A4I/carebridge/data_plane/sql/03_demographic_audit_table.sql)
Creates `a4i-fulton-2026.external_demographic_audit.tract_demographics_audit`:
- Physically isolated in the `external_demographic_audit` dataset (`audit_only_toolset`).
- Exposes `geo_id`, `county_fips`, `total_pop`, `rpl_theme3`, `rpl_themes`, `pct_minority`, `pct_black`, `pct_hispanic`, `pct_asian`, `pct_white_non_hispanic`, and `'POST_HOC_AUDITOR_ONLY_FORBIDDEN_IN_PLANNER' AS access_policy_tag`.
- Never queried by or visible to Evidence Agents A/B, the Evidence Validator, the 4-Stop Optimizer, or the Siting Planner Agent.

---

## Verification

Verified in [`tests/test_01_bigquery_mcp.py`](file:///Users/dvt112/Downloads/A4I/tests/test_01_bigquery_mcp.py) (`test_05_sql_files_yaml_config_and_otel_telemetry`).
