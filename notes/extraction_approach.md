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

### Handling a mid-run connection drop

During the real backfill run, the script crashed at page 109 (2,160,000 rows already written) with `requests.exceptions.ConnectionError: RemoteDisconnected('Remote end closed connection without response')` — a transient network/server-side disconnect, not a bug in the extraction logic itself.

Because the raw data was being written incrementally as JSON Lines, the rows already fetched were safe on disk and uncorrupted (verified: exactly 2,160,000 complete lines, cleanly terminated). The script was updated to detect this automatically: on startup, it counts the existing lines in the output file and resumes pagination from that offset, opening the file in append (`"a"`) mode rather than overwrite (`"w"`) mode. This makes re-running the script after a crash safe and idempotent-by-offset — no manual recalculation needed.

This does not add general retry-on-failure logic (automatically retrying a failed request without restarting the whole script) — that remains deferred to the planned failure-testing work (step 8), where it will be handled more deliberately alongside other idempotency testing.

### An open-ended window is a moving target

The original `$where` clause (`created_date >= '2025-10-01T00:00:00'`) had no upper bound. That's a distinct problem from the pagination-determinism issue above: even with `$order` fixed, a window with no end date keeps growing every day the extraction spans, because new rows created since the target count was last measured satisfy the same filter. Concretely, the original target of 4,007,508 rows (measured October 6) was already stale by October 8 — two more days of new 311 complaints had entered the window.

Fixed by closing the window to a fixed historical range: `created_date >= '2025-10-01T00:00:00' AND created_date < '2026-10-01T00:00:00'`. This makes the backfill target a fixed number that will never drift, however many days the extraction takes. The actively-changing recent tail (October 2026 onward, as of this writing) is deliberately excluded from this one-time backfill — it will be picked up later by the incremental, watermark-based load (ADR-0002 / step 4), which is exactly what that mechanism is for. Re-running the `count(*)` query against the new, bounded `$where` gave the corrected, now-stable target: **3,963,867 rows**.

Because pagination runs in ascending `created_date` order, adding an upper bound only trims rows off the tail of the result set — it doesn't reorder or renumber anything before the new cutoff. This meant the backfill already in progress (over 2 million rows in) did not need to be restarted from scratch; the existing resume-by-offset logic continued to work unchanged once the `$where` clause was updated.

### A `timeout`, and a genuinely flaky run

A `timeout=60` argument was added to the `requests.get(...)` call after the resume logic revealed a second failure mode: without a timeout, a request that never gets a response at all (as opposed to one the server actively closes) can hang indefinitely, with nothing to force it to give up. This was observed directly — a resumed run sat with zero progress for several minutes before being manually interrupted.

With the timeout in place, the same category of problem now fails fast and cleanly (`requests.exceptions.ReadTimeout`) instead of hanging silently — but it still crashes the script rather than retrying automatically, which remains correctly deferred to step 8. In practice, this particular backfill run hit several of these read timeouts in relatively quick succession (roughly every 10-15 pages at one point), suggesting the Socrata API itself was being intermittently slow or flaky during this window, rather than a one-off fluke. Recovery each time was simply re-running the script, which resumed cleanly from wherever the previous attempt left off. This repeated pattern is itself a point in favor of building real retry-with-backoff logic sooner rather than later in step 8, since manually re-running the script several times in a row is a tedious, error-prone substitute for the real thing.

### Switching from offset to keyset pagination

Partway through the backfill, failures began happening sooner after each resume (page 109 into a fresh run, then ~page 13 after one resume, then immediately on the next two). One hypothesis: `$offset`/`$limit` pagination combined with `$order` typically requires the server to sort (or at least scan) the entire matching result set up to the requested offset on every single call, which gets progressively more expensive as the offset grows — unlike a cursor-based approach, which can seek directly to a position via an index regardless of how deep into the result set that position is.

The fix: switched to keyset pagination. Instead of tracking a row count and sending `$offset`, the script now tracks the last row's `created_date` and `unique_key` and filters for "strictly after that point" on every call:

```
(created_date > '<last_date>') OR (created_date = '<last_date>' AND unique_key > '<last_key>')
```

The `OR` clause (rather than a plain `created_date > '<last_date>'`) matters for the same reason `$order` needed `unique_key` as a tiebreaker in the first place: many rows share the same `created_date`, so a plain `>` comparison would silently skip any remaining rows tied with the last one already written. Resuming this way only requires reading the last line of the existing output file (to get its `created_date`/`unique_key`) rather than counting all rows, and — like the offset-based resume logic before it — required no re-extraction of data already on disk.

**Caveat, for intellectual honesty:** switching to keyset pagination did not eliminate the timeouts. The very first call of the keyset version timed out immediately, with no offset-driven cost to blame. This is evidence against the "cost grows with offset depth" theory being the main (or only) cause of the day's repeated failures — if it were, the keyset version should have been largely immune, and it wasn't. Keyset pagination remains the structurally correct choice (it avoids a real, known anti-pattern regardless of whether it was the dominant cause here), but the more likely explanation for today's specific pattern of repeated timeouts is that the Socrata API itself was intermittently slow or degraded during this extraction window, independent of the pagination strategy used.

### Backfill complete

The backfill finished successfully: **3,963,880 rows** written to `raw_data/nyc311_backfill_2025-10-01.jsonl`, covering the bounded window `2025-10-01T00:00:00` through `2026-09-30T23:59:59`.

This is 13 rows more than the target count measured earlier (3,963,867). That's expected, not a bug: the target was counted at one point in time, but this is real-world operational data — a row with a `created_date` inside the already-closed window can still be entered into the source system after the fact (e.g. a complaint that occurred near the end of September but wasn't logged until days later). So the exact count of rows matching a fixed historical date range can drift slightly between when it's measured and when extraction finishes, even though the window itself never changes. A ~0.0003% difference here is well within that expected drift.

What this window deliberately does *not* cover: anything from October 1, 2026 onward. That gap (and all future data) is intentionally left for the incremental, watermark-based loader described in ADR-0002 — the backfill's job was a one-time historical load up to a fixed cutoff, not an ongoing sync.

Final script state: keyset (cursor-based) pagination on `(created_date, unique_key)`, plus a lightweight retry wrapper (up to 3 attempts, 5s delay) around each page request. The retry wrapper absorbed several `ReadTimeoutError`s automatically during the final run without stopping the script — confirming that the day's repeated timeouts really were transient/intermittent rather than a structural problem with the request pattern.
