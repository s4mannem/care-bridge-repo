-- carebridge/data_plane/sql/01_marta_gtfs_views.sql
-- Creates the Saturday MARTA GTFS transit access view for Fulton County (13121) census tracts.
-- IMPORTANT: Stop proximity measures Saturday transit stop presence within 400m,
-- NOT door-to-door clinic journey time. Access Across America transit travel-time matrices
-- are excluded due to CC BY-NC license boundary.

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
