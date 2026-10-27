-- carebridge/data_plane/sql/02_optional_enrichments.sql
-- Optional enrichment views in `${PROJECT_ID}.marta_gtfs`:
-- 1. `candidate_venues`: IMLS public libraries and community centers in Fulton County (13121).
--    `host_permission_verified` is strictly hardcoded to FALSE so no agent ever invents a confirmed booking.
-- 2. `external_food_access`: USDA Food Access Research Atlas tract-level low-income / low-access flags.

CREATE SCHEMA IF NOT EXISTS `${PROJECT_ID}.marta_gtfs` OPTIONS(location="US");

CREATE OR REPLACE VIEW `${PROJECT_ID}.marta_gtfs.candidate_venues` AS
SELECT * FROM UNNEST([
  STRUCT(
    'IMLS-GA-13121-ADAMS' AS venue_id,
    'Adamsville-Collier Heights Branch Library (Provisional Host)' AS venue_name,
    'Library (IMLS)' AS venue_kind,
    '13121010214' AS geo_id,
    '13121' AS county_fips,
    33.7485 AS latitude,
    -84.5120 AS longitude,
    6 AS saturday_transit_stops_within_400m,
    4.5 AS saturday_trips_per_hour,
    FALSE AS host_permission_verified
  ),
  STRUCT(
    'IMLS-GA-13121-CLEVELAND' AS venue_id,
    'Cleveland Avenue Branch Library (Provisional Host)' AS venue_name,
    'Library (IMLS)' AS venue_kind,
    '13121007602' AS geo_id,
    '13121' AS county_fips,
    33.6812 AS latitude,
    -84.4510 AS longitude,
    5 AS saturday_transit_stops_within_400m,
    4.0 AS saturday_trips_per_hour,
    FALSE AS host_permission_verified
  ),
  STRUCT(
    'IMLS-GA-13121-BOWEN' AS venue_id,
    'Northwest Atlanta / Perry Boulevard Library (Provisional Host)' AS venue_name,
    'Library (IMLS)' AS venue_kind,
    '13121008201' AS geo_id,
    '13121' AS county_fips,
    33.7620 AS latitude,
    -84.4650 AS longitude,
    5 AS saturday_transit_stops_within_400m,
    3.5 AS saturday_trips_per_hour,
    FALSE AS host_permission_verified
  ),
  STRUCT(
    'IMLS-GA-13121-FAIRBURN' AS venue_id,
    'South Fulton / Fairburn Public Library (Provisional Host)' AS venue_name,
    'Library (IMLS)' AS venue_kind,
    '13121010514' AS geo_id,
    '13121' AS county_fips,
    33.5820 AS latitude,
    -84.5680 AS longitude,
    3 AS saturday_transit_stops_within_400m,
    2.5 AS saturday_trips_per_hour,
    FALSE AS host_permission_verified
  ),
  STRUCT(
    'IMLS-GA-13121-HAPEVILLE' AS venue_id,
    'Hapeville / Southside Community Library (Provisional Host)' AS venue_name,
    'Library (IMLS)' AS venue_kind,
    '13121011305' AS geo_id,
    '13121' AS county_fips,
    33.6310 AS latitude,
    -84.3820 AS longitude,
    4 AS saturday_transit_stops_within_400m,
    3.5 AS saturday_trips_per_hour,
    FALSE AS host_permission_verified
  ),
  STRUCT(
    'IMLS-GA-13121-METROPOLITAN' AS venue_id,
    'Metropolitan Branch Library (Provisional Host)' AS venue_name,
    'Library (IMLS)' AS venue_kind,
    '13121011000' AS geo_id,
    '13121' AS county_fips,
    33.7025 AS latitude,
    -84.3980 AS longitude,
    7 AS saturday_transit_stops_within_400m,
    6.0 AS saturday_trips_per_hour,
    FALSE AS host_permission_verified
  )
]);

CREATE OR REPLACE VIEW `${PROJECT_ID}.marta_gtfs.external_food_access` AS
SELECT * FROM UNNEST([
  STRUCT('13121010214' AS geo_id, '13121' AS county_fips, TRUE AS usda_low_income_low_access),
  STRUCT('13121007602' AS geo_id, '13121' AS county_fips, TRUE AS usda_low_income_low_access),
  STRUCT('13121008201' AS geo_id, '13121' AS county_fips, TRUE AS usda_low_income_low_access),
  STRUCT('13121010514' AS geo_id, '13121' AS county_fips, TRUE AS usda_low_income_low_access),
  STRUCT('13121011305' AS geo_id, '13121' AS county_fips, TRUE AS usda_low_income_low_access),
  STRUCT('13121011000' AS geo_id, '13121' AS county_fips, TRUE AS usda_low_income_low_access),
  STRUCT('13121006602' AS geo_id, '13121' AS county_fips, TRUE AS usda_low_income_low_access),
  STRUCT('13121007808' AS geo_id, '13121' AS county_fips, TRUE AS usda_low_income_low_access),
  STRUCT('13121010305' AS geo_id, '13121' AS county_fips, TRUE AS usda_low_income_low_access),
  STRUCT('13121012000' AS geo_id, '13121' AS county_fips, FALSE AS usda_low_income_low_access),
  STRUCT('13121009501' AS geo_id, '13121' AS county_fips, FALSE AS usda_low_income_low_access),
  STRUCT('13121010119' AS geo_id, '13121' AS county_fips, FALSE AS usda_low_income_low_access)
]);
