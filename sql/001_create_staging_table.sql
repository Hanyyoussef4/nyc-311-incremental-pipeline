-- Step 4: Postgres staging table for NYC 311 Service Requests
-- Schema: staging.staging_311_requests
--
-- Design notes:
--   - 48 columns match the dataset's official schema (confirmed via Socrata's
--     metadata API, the official NYC 311 data dictionary, and a full scan of
--     the backfilled data -- see notes/nyc311_dataset_schema_reference.md).
--   - raw_payload (JSONB), _loaded_at, _source_file are pipeline-owned
--     metadata columns, not part of the source schema.
--   - Append-only by design: every load inserts, nothing is ever updated or
--     deleted. Composite primary key (unique_key, _loaded_at) is what makes
--     that safe -- see notes/decisions/0007-staging-append-only-history.md
--     for the full reasoning (preserves history under the UPSERT fact table).
--   - All numeric-looking fields (bbl, latitude, longitude, the
--     x/y_coordinate_state_plane fields, the computed_region_* fields) are
--     kept as TEXT here on purpose: staging's job is to shape the raw dump
--     into a table, not to cast or interpret values. Real type casting is a
--     transform-step (step 5) decision.

CREATE SCHEMA IF NOT EXISTS staging;

CREATE TABLE staging.staging_311_requests (
    unique_key TEXT,
    address_type TEXT,
    agency TEXT,
    agency_name TEXT,
    complaint_type TEXT,
    descriptor TEXT,
    descriptor_2 TEXT,
    location_type TEXT,
    incident_zip TEXT,
    incident_address TEXT,
    street_name TEXT,
    cross_street_1 TEXT,
    cross_street_2 TEXT,
    intersection_street_1 TEXT,
    intersection_street_2 TEXT,
    city TEXT,
    landmark TEXT,
    facility_type TEXT,
    status TEXT,
    resolution_description TEXT,
    community_board TEXT,
    council_district TEXT,
    police_precinct TEXT,
    bbl TEXT,
    borough TEXT,
    x_coordinate_state_plane TEXT,
    y_coordinate_state_plane TEXT,
    open_data_channel_type TEXT,
    park_facility_name TEXT,
    park_borough TEXT,
    vehicle_type TEXT,
    taxi_company_borough TEXT,
    taxi_pick_up_location TEXT,
    bridge_highway_name TEXT,
    bridge_highway_direction TEXT,
    road_ramp TEXT,
    bridge_highway_segment TEXT,
    latitude TEXT,
    longitude TEXT,
    computed_region_f5dn_yrer TEXT,
    computed_region_yeji_bk3q TEXT,
    computed_region_sbqj_enih TEXT,
    computed_region_92fq_4b7q TEXT,
    created_date TIMESTAMP,
    closed_date TIMESTAMP,
    due_date TIMESTAMP,
    resolution_action_updated_date TIMESTAMP,
    location JSONB,
    raw_payload JSONB,
    _loaded_at TIMESTAMP DEFAULT NOW(),
    _source_file TEXT,
    PRIMARY KEY (unique_key, _loaded_at)
);

-- Backs the "current state" derivation query from ADR-0007:
--   SELECT DISTINCT ON (unique_key) *
--   FROM staging.staging_311_requests
--   ORDER BY unique_key, _loaded_at DESC;
-- Standard B-tree (Postgres default) -- naturally supports this ordered,
-- per-group lookup pattern.
CREATE INDEX idx_staging_311_current
ON staging.staging_311_requests (unique_key, _loaded_at DESC);
