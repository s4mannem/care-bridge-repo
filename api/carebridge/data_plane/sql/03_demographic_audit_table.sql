-- carebridge/data_plane/sql/03_demographic_audit_table.sql
-- Protected post-hoc demographic audit table in `${PROJECT_ID}.external_demographic_audit`.
-- SECURITY BOUNDARY: Dataset ACLs grant `roles/bigquery.dataViewer` ONLY to the Independent
-- Equity & Rigor Auditor service account. Physically excluded from Evidence and Planner toolsets.

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
