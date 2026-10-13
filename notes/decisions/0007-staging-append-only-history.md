# ADR-0007: Append-Only Staging to Preserve History Under a UPSERT Fact Table

**Status:** Accepted

**Context:**

ADR-0001 established that the fact table uses UPSERT (not append-only), keeping one row per `unique_key`, always reflecting the latest known state. This is the right choice for the fact table — most reporting needs (current backlog, resolution times, agency volume) only care about current state, and UPSERT keeps that table small and fast.

But UPSERT has a side effect: every time a row is updated (e.g., a complaint's `status` goes from "Open" to "Closed"), the previous value is gone the moment the new one lands. If nothing else in the pipeline preserves prior versions, there would be no way to answer questions like "what did this case look like last month" or reconstruct the sequence of changes a row went through — a form of data loss, even though each individual load is working correctly.

Two alternatives were considered to address this:

1. **Full SCD Type 2 in the fact table itself** (new row per change, `valid_from`/`valid_to` effective-dating, `is_current` flag) — the traditional way dimensional modeling handles this. Rejected as overkill for this project: it adds real complexity (surrogate keys, close-out logic for old rows, more complex joins for consumers) that isn't justified by the reporting needs this project actually targets.
2. **A second, separate "current" staging table alongside a historical one** — rejected because it would duplicate UPSERT logic across two layers of the pipeline (once for staging-current, again for the fact table) for no real benefit, and risks the two tables drifting out of sync with each other.

**Decision:**

The staging table is loaded **append-only** — every pipeline run inserts new rows, never updates or deletes existing ones, keyed by `(unique_key, _loaded_at)` rather than `unique_key` alone. This means staging naturally accumulates a full, queryable history of every version of every row ever loaded, directly in Postgres.

The fact table (step 5) is unaffected by this decision — it remains UPSERT, current-state-only, exactly as ADR-0001 already established.

If "current state" is ever needed directly from staging (e.g., for debugging or an ad hoc check, rather than through the fact table), it can be derived on read with:

```sql
SELECT DISTINCT ON (unique_key) *
FROM staging_311_requests
ORDER BY unique_key, _loaded_at DESC;
```

A composite index on `(unique_key, _loaded_at DESC)` keeps this efficient. This is a standard B-tree index (Postgres's default index type) — the right choice here since B-tree naturally supports the ordered, per-group lookup that `DISTINCT ON` relies on. No specialized index type (GIN/GiST/BRIN) is needed for this use case.

This query is meant for occasional use, not the main query path — the fact table remains the table consumers actually query often for current state, since it's cheap to query by design (incrementally maintained) rather than recomputed from full history each time.

**Consequences:**

- Staging grows unbounded over time (every load adds rows, nothing is ever removed) — acceptable for this project's scope and timeframe, but would need a retention/archival policy in a longer-lived production system.
- Full row-level history is preserved and queryable in Postgres without ever needing to re-extract from the Socrata API or re-parse old raw `.jsonl` files.
- No duplicated UPSERT logic — UPSERT happens exactly once in the pipeline, at the fact table build step, keeping that logic in a single place.
- Staging and the fact table have clearly different jobs: staging optimizes for cheap writes and complete history; the fact table optimizes for cheap reads and current state.
