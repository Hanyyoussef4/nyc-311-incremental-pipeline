# ADR-0002: Watermark strategy — use :updated_at for incremental loads

## Status
Accepted

## Context
A naive full-refresh load of ~22.5M rows every run doesn't scale and
doesn't reflect how this dataset actually behaves. We needed a reliable
way to ask the source "what's new or changed since my last successful
run?" rather than re-pulling everything each time.

Two candidate fields were considered: `created_date` (when a request was
first filed) and `:updated_at` (Socrata's system field marking when a
row last changed in any way). `created_date` alone was ruled out: the
exploration sample-bias finding showed that fields like lat/long and the
computed-region columns are populated by a delayed backend process
*after* a request is created — meaning a pipeline filtering only on
`created_date` would permanently miss those later backfills once the
initial load window passed.

`:updated_at` was tested directly before being trusted: a control case
(`:updated_at` > a future date) correctly returned 0 rows, and a realistic
case (`:updated_at` > one week ago) returned a small, plausible ~3% of
the dataset — confirming the field behaves as a genuine, filterable
watermark (see `notes/data_exploration.md`).

## Decision
Each incremental run will query Socrata with
`$where :updated_at > <last_successful_watermark>`, where
`<last_successful_watermark>` is the maximum `:updated_at` value
successfully processed by the previous run. This value will be persisted
in a control/state table (not a file or hardcoded value), read at the
start of each run and only updated after that run completes successfully.

## Consequences
- Requires a small control table (e.g. `pipeline_control` or similar)
  tracking the last successful watermark — this is new infrastructure the
  pipeline needs beyond just the fact/dimension tables.
- The watermark is only advanced after a run fully succeeds. If a run
  fails partway through, the next run re-uses the same watermark and
  re-processes the same window — combined with the UPSERT grain from
  ADR-0001, this makes retries safe (idempotent) rather than creating
  duplicates.
- This approach naturally captures both brand-new requests and updates to
  existing ones (status changes, closures, and delayed backfills like
  geocoding) in the same mechanism — no separate logic needed for "new"
  vs. "changed" rows.
- Open risk to watch for during implementation: a row could be updated by
  Socrata *during* the extraction window (between when the query starts
  and finishes), right at the watermark boundary. A common mitigation is
  a small overlap/safety buffer (e.g., re-querying a few minutes earlier
  than the exact last watermark) rather than trusting an exact cutoff —
  to be handled when building the actual extract logic (step 4), not
  decided here.
