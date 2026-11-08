-- Step 4: control schema for the incremental pipeline
-- Built 2026-10-19/20 directly against the database; captured here
-- as a migration file 2026-11-07.
--
-- Two deliberately separate tables:
--   - pipeline_runs: append-only audit log, one row per run attempt.
--   - pipeline_state: single current watermark pointer per pipeline,
--     not history -- this is what the loader reads to know where it
--     left off. Keeping it separate from pipeline_runs avoids needing
--     a "fake run zero" row just to seed the bootstrap case.

CREATE SCHEMA IF NOT EXISTS control;

CREATE TABLE control.pipeline_runs (
    run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pipeline_name TEXT NOT NULL,
    watermark_start TIMESTAMPTZ NOT NULL,
    watermark_end TIMESTAMPTZ NOT NULL,
    run_started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    run_finished_at TIMESTAMPTZ,
    rows_pulled INTEGER NOT NULL DEFAULT 0,
    rows_inserted INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'RUNNING'
        CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED')),
    notes TEXT,
    CONSTRAINT valid_watermark_window CHECK (watermark_end > watermark_start),
    CONSTRAINT valid_row_counts CHECK (
        rows_pulled >= 0 AND rows_inserted >= 0 AND rows_inserted <= rows_pulled
    ),
    CONSTRAINT completed_run_has_finish_time CHECK (
        status = 'RUNNING' OR run_finished_at IS NOT NULL
    ),
    CONSTRAINT valid_run_duration CHECK (
        run_finished_at IS NULL OR run_finished_at >= run_started_at
    )
);

CREATE TABLE control.pipeline_state (
    pipeline_name TEXT PRIMARY KEY,
    last_watermark TIMESTAMPTZ NOT NULL,
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
