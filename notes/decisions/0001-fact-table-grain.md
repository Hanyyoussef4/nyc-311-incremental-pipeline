# ADR-0001: Fact table grain — one row per unique_key

## Status
Accepted

## Context
The NYC 311 dataset is a live, growing table of ~22.5M service request
records. Before designing the star schema, we needed to know what a single
row in the fact table represents — specifically, whether the dataset's
`unique_key` field could be trusted as a true one-row-per-request
identifier, or whether duplicate `unique_key` values existed that would
require a different grain (e.g., one row per request *per update*, or
per some other combination of fields).

## Decision
The fact table (`fact_service_requests`) will have exactly one row per
`unique_key`. This was verified, not assumed: a server-side aggregation
query (`$group unique_key`, `$having count(*) > 1`) run against the full
~22.5M-row dataset (no `$where`/`$limit` restricting the scope) returned
zero results, confirming `unique_key` never repeats anywhere in the
dataset (see `notes/data_exploration.md`).

## Consequences
- `unique_key` becomes the fact table's primary key.
- When a request is updated after creation (status change, closure, a
  backfilled lat/long from geocoding — see the sample-bias finding in
  exploration), the pipeline will UPSERT that existing row rather than
  insert a new one. This grain decision is what makes UPSERT the correct
  loading strategy, rather than append-only.
- This grain choice depends on the watermark strategy (ADR-0002,
  `:updated_at`) to actually detect when an existing row needs updating —
  the two decisions work together: grain says "one row per request,"
  watermark says "how we know a row changed."
- If a future data refresh ever revealed a duplicate `unique_key` (e.g., a
  Socrata data quality regression), this grain assumption would break and
  would need to be revisited — worth a periodic sanity check, not just a
  one-time verification.
- This grain does not preserve status history (e.g., that a request was
  once Open, then In Progress, before becoming Closed) — only its current
  state. If historical tracking is ever needed, that would be a
  deliberate future upgrade (a separate history table, or converting this
  fact table to an SCD Type 2 style design), not something this grain
  currently supports.
