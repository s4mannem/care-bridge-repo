# `carebridge.mocks` — Fulton County (`13121`) Realistic Fixtures

The [`carebridge/mocks/`](file:///Users/dvt112/Downloads/A4I/carebridge/mocks/__init__.py) package provides deterministic, domain-grounded fixtures for **Fulton County, Georgia (`county_fips = "13121"`)** in [`fulton_fixtures.py`](file:///Users/dvt112/Downloads/A4I/carebridge/mocks/fulton_fixtures.py). These fixtures power offline unit/certification tests and local demo mode when live BigQuery credentials are not configured.

---

## Geographic & Clinical Realism

[`FULTON_TRACT_HEALTH_RECORDS`](file:///Users/dvt112/Downloads/A4I/carebridge/mocks/fulton_fixtures.py#L29-L263) contains **12 representative 11-character census tracts** spanning Fulton County's North-South health and transit gradient:

| Tract GEOID | Sub-County Area / Neighborhood | Pop | Uninsured (`18–64`) | Routine Checkup (`pct_checkup`) | Preventive Gap (`100 - checkup`) | Safety-Net Distance (km) | No Vehicle (`%`) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `13121010510` | South Fulton / Old National Hwy | 5,420 | 24.8% | 71.2% | 28.8% | 6.8 km | 18.4% |
| `13121010214` | South Fulton / Campbellton Rd | 4,890 | 23.1% | 72.5% | 27.5% | 6.2 km | 21.0% |
| `13121011202` | Tri-Cities / East Point & College Park | 4,310 | 22.4% | 73.0% | 27.0% | 5.4 km | 24.5% |
| `13121008400` | Westside Atlanta / Bankhead | 3,650 | 21.9% | 73.8% | 26.2% | 4.9 km | 28.2% |
| `13121007808` | Southwest Atlanta / Cascade Corridor | 4,760 | 19.8% | 74.5% | 25.5% | 5.7 km | 16.9% |
| `13121008500` | Westview / Hollowell Pkwy | 3,490 | 20.5% | 74.1% | 25.9% | 4.6 km | 25.1% |
| `13121010305` | Fairburn / Union City Corridor | 5,810 | 19.2% | 75.0% | 25.0% | 7.4 km | 12.8% |
| `13121006700` | Southeast Atlanta / Lakewood | 3,920 | 21.0% | 73.6% | 26.4% | 4.8 km | 22.7% |
| `13121005501` | Pittsburgh / Mechanicsville | 3,280 | 20.1% | 74.4% | 25.6% | 3.5 km | 26.4% |
| `13121001901` | Downtown / Midtown Connector | 4,150 | 11.4% | 78.9% | 21.1% | 1.8 km | 21.5% |
| `13121009502` | Buckhead / Peachtree Hills | 5,120 | 5.8% | 83.4% | 16.6% | 2.9 km | 6.2% |
| `13121011610` | North Fulton / Alpharetta | 6,340 | 5.2% | 84.7% | 15.3% | 4.1 km | 3.1% |

---

## Real-World Dataset Nuances Encoded in Fixtures

1. **HPSA Shortage Area vs. Shortage Facility Nuance**:
   - In [`build_mock_health_evidence()`](file:///Users/dvt112/Downloads/A4I/carebridge/mocks/fulton_fixtures.py#L431-L450), Fulton County has `shortage_areas_count = 0` (0 geographic Primary Care HPSA polygons) alongside `shortage_facilities_count = 6` (6 designated safety-net shortage facilities, max HPSA score `19.0`) and `care_sites_count = 85` (`41` safety-net sites).
   - [`FULTON_CARE_SITES`](file:///Users/dvt112/Downloads/A4I/carebridge/mocks/fulton_fixtures.py#L266-L310) includes HRSA `tot_oper_hr_per_week` (`20.0` to `45.0` hrs/wk) and zero administrative PII.
2. **4-County Health Service Area (`disease_weekly`)**:
   - [`FULTON_REGIONAL_DISEASE`](file:///Users/dvt112/Downloads/A4I/carebridge/mocks/fulton_fixtures.py#L313-L327) models `hsa_name = "Atlanta Regional HSA (Fulton, Ga)"` covering `"Fulton, DeKalb, Clayton, Gwinnett"` with `SpatialGrain.MULTI_COUNTY_HSA`.
3. **Provisional Candidate Host Venues (IMLS Libraries)**:
   - [`FULTON_CANDIDATE_VENUES`](file:///Users/dvt112/Downloads/A4I/carebridge/mocks/fulton_fixtures.py#L330-L386) provides 6 public library branches across South Fulton, Campbellton Road, East Point, Adamsville-Collier Heights, Cascade, and Fairburn—all with `host_permission_verified = False`.
4. **Protected Post-Hoc Demographic Audit Fixtures**:
   - [`DEMOGRAPHIC_AUDIT_FIXTURES`](file:///Users/dvt112/Downloads/A4I/carebridge/mocks/fulton_fixtures.py#L389-L428) stores `rpl_theme3`, `rpl_themes`, `pct_minority`, `pct_black`, and `pct_hispanic` for each of the 12 tracts. This dictionary is physically separated from all Evidence/Planner fixtures and is only read by `BigQueryMCPBridge.mcp_query_posthoc_demographic_audit()` when called by `equity_rigor_auditor`.

---

## Builder Functions

| Function | Returns | Purpose |
| :--- | :--- | :--- |
| [`build_mock_health_evidence(county_fips="13121")`](file:///Users/dvt112/Downloads/A4I/carebridge/mocks/fulton_fixtures.py#L431-L450) | [`HealthEvidence`](file:///Users/dvt112/Downloads/A4I/carebridge/contracts/evidence_models.py#L128-L157) | Race-blind health & access evidence for 12 Fulton tracts |
| [`build_mock_mobility_evidence(county_fips="13121", include_optional=True)`](file:///Users/dvt112/Downloads/A4I/carebridge/mocks/fulton_fixtures.py#L453-L515) | [`MobilityEvidence`](file:///Users/dvt112/Downloads/A4I/carebridge/contracts/evidence_models.py#L205-L227) | Saturday MARTA GTFS stop proximity, USDA food access, and IMLS venues (or degraded empty state when `include_optional=False`) |
| [`build_mock_evidence_report(county_fips="13121")`](file:///Users/dvt112/Downloads/A4I/carebridge/mocks/fulton_fixtures.py#L518-L558) | [`EvidenceReport`](file:///Users/dvt112/Downloads/A4I/carebridge/contracts/evidence_models.py#L246-L273) | Validated data-quality gate report with 4 mandatory grain caveats |
| [`build_mock_draft_plan(county_fips="13121", revision_number=0)`](file:///Users/dvt112/Downloads/A4I/carebridge/mocks/fulton_fixtures.py#L561-L685) | [`DraftPlan`](file:///Users/dvt112/Downloads/A4I/carebridge/contracts/plan_models.py#L150-L185) | 4 distinct Saturday stops (`>= 5.0 km` apart) + 2 runner-up explanations (`#5` Cascade `13121007808`, `#6` Fairburn `13121010305`) |
| [`build_mock_audit_report(revision_audited=0, verdict=AuditVerdict.APPROVED)`](file:///Users/dvt112/Downloads/A4I/carebridge/mocks/fulton_fixtures.py#L688-L734) | [`AuditReport`](file:///Users/dvt112/Downloads/A4I/carebridge/contracts/audit_models.py#L85-L116) | Complete audit report with post-hoc demographic comparison |
| [`build_mock_outreach_messages(county_fips="13121")`](file:///Users/dvt112/Downloads/A4I/carebridge/mocks/fulton_fixtures.py#L737-L793) | [`OutreachMessages`](file:///Users/dvt112/Downloads/A4I/carebridge/contracts/outreach_models.py#L68-L96) | Bilingual EN/ES notices and runner-up explanations |
| [`build_mock_plan_response(request_id="req-demo-13121")`](file:///Users/dvt112/Downloads/A4I/carebridge/mocks/fulton_fixtures.py#L796-L814) | [`PlanResponse`](file:///Users/dvt112/Downloads/A4I/carebridge/contracts/api_models.py#L59-L83) | Full end-to-end API response bundle |
