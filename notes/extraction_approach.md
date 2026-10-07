## Extraction approach — initial backfill

This note documents how the initial backfill (trailing 12 months, `created_date >= 2025-10-01`, target ~4,007,508 rows) was pulled from the Socrata API, and two things learned along the way.

### Why pagination was needed

Socrata's SODA API defaults to returning only 1,000 rows per request when `$limit` isn't specified, and caps out at 50,000 on this dataset's endpoint version. Pulling ~4 million rows therefore requires looping over the API with `$limit`/`$offset`, incrementing `$offset` each call until a request returns fewer rows than asked for (the signal that extraction is complete). ([Socrata SODA API docs — `$limit`](https://dev.socrata.com/docs/queries/limit.html))

### Batch size: tested, not guessed

Rather than picking a `$limit` value arbitrarily, throughput was measured directly against the live API:

- `$limit=10000`: averaged roughly 500–890 rows/sec across several measured windows during a real run
- `$limit=20000`: averaged roughly 870–895 rows/sec across several measured windows

20,000 was adopted as the batch size for this backfill: it roughly halves the number of API calls versus 10,000 (reducing fixed per-call overhead — connection setup, auth, query parsing) without measurably hurting per-row throughput, and stays well short of the 50,000 max, where payload size and timeout risk increase meaningfully for a ~30-column, text-heavy row like this dataset's.

### Pagination determinism: a bug caught mid-run

The first version of the extraction loop used `$limit`/`$offset` with no explicit `$order`. Partway through a real run (~38% complete), it became clear this was a mistake: **`$offset`-based pagination is only reliable if the server returns rows in a stable, deterministic order across calls.** Without an explicit `$order`, that ordering isn't guaranteed — and this dataset updates continuously (daily), with the backfill's own window (`created_date >= 2025-10-01`) including the present day. That means new rows were being created and potentially inserted into the underlying result set *while the extraction was running*.

Concretely, the risk: if a row got inserted "before" the current pagination position between two calls, every subsequent call's results could shift — producing either a duplicate row (returned twice, in two different pages) or a skipped row (pushed past the offset boundary and never fetched at all), with no error or warning to indicate it happened.

The fix was to add an explicit, deterministic sort order:

```
"$order": "created_date, unique_key"
```

`created_date` alone isn't sufficient as a sort key since many rows share the same value; adding `unique_key` (the table's confirmed primary key — see ADR-0001) as a tiebreaker guarantees a fully deterministic ordering, making the pagination safe to run against a live, changing table. The in-progress run was stopped and restarted from scratch once this fix was in place, rather than letting a run with unknown data-integrity risk finish silently.

### Raw landing format: JSON Lines

Each page of results is written to `raw_data/` as it arrives, one JSON object per line (`.jsonl`), rather than accumulated in memory and written once as a single JSON array at the end. This keeps memory usage flat regardless of total row count, and means a mid-run failure only loses the as-yet-unwritten tail of the run rather than all of it — relevant since no retry/resume logic exists yet for this extraction step.

See `scripts/backfill_extract.py` for the full implementation.
