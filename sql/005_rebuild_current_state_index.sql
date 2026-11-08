-- Rebuilds idx_staging_311_current to match the staging table's
-- corrected primary key (see sql/004 and ADR-0007's 2026-10-31 update).
--
-- The original index was built on (unique_key, _loaded_at DESC) to back
-- ADR-0007's "current state" derivation query. Since _loaded_at is pinned
-- once per transaction rather than per row, it can't reliably distinguish
-- between two genuinely different versions of the same complaint loaded
-- within the same run -- the same problem that motivated the primary key
-- correction. updated_at DESC is the correct ordering column instead,
-- since Socrata only advances updated_at when something actually changed.

DROP INDEX staging.idx_staging_311_current;

CREATE INDEX idx_staging_311_current
ON staging.staging_311_requests (unique_key, updated_at DESC);
