-- Step 4: staging primary key correction + data_maintenance_log table
-- Both run directly against the database 2026-10-31; captured here
-- as a migration file 2026-11-07.
--
-- PK fix: _loaded_at is pinned once per transaction (NOW()), not per
-- row, so two genuinely distinct Socrata revisions of the same
-- complaint loaded in the same transaction could collide on the old
-- key. updated_at is the real natural per-version key.

ALTER TABLE staging.staging_311_requests DROP CONSTRAINT staging_311_requests_pkey;
ALTER TABLE staging.staging_311_requests ADD PRIMARY KEY (unique_key, updated_at);

-- Append-only log of manual corrections, kept separate from
-- pipeline_runs so that table never needs retroactive mutation.
-- executed_at has no default on purpose, forcing every insert to
-- consciously supply the real execution time.
CREATE TABLE IF NOT EXISTS control.data_maintenance_log (
    maintenance_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    table_name TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('DELETE','INSERT','UPDATE')),
    reason TEXT NOT NULL,
    rows_affected BIGINT NOT NULL CHECK (rows_affected >= 0),
    executed_at TIMESTAMPTZ NOT NULL,
    logged_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    related_run_id BIGINT NULL REFERENCES control.pipeline_runs(run_id),
    notes TEXT
);
