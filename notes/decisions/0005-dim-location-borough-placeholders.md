# ADR-0005: dim_location — explicit placeholder rows for missing/unspecified borough

## Status
Accepted

## Context
Data exploration found 7 distinct `borough` groups in the full dataset: 5
real boroughs (Bronx, Brooklyn, Manhattan, Queens, Staten Island), the
literal string `Unspecified` (40,831 rows), and 38,433 rows where the
`borough` key is missing entirely from the raw API response — Socrata
omits keys for empty fields rather than returning `null` (see
`notes/data_exploration.md`).

These are two genuinely different situations, not one: `Unspecified` means
the source system positively recorded "no borough was given" — a
deliberate value. A missing key means the field was never returned for
that row at all, a different signal with a possibly different root cause
(worth a future check on whether it correlates with recency, the same way
the geocoding/computed-region lag did — not required to make this
decision).

Every one of the ~22.5M fact rows needs a foreign key into the location
dimension, including these ~79,000 combined "no real borough" rows. A
decision is needed for how the dimension represents that, without losing
the distinction the exploration found or leaving foreign keys null.

## Decision
`dim_location` will include two explicit placeholder rows — not a
nullable foreign key, and not a single collapsed "Unknown" bucket — one
representing `Unspecified` (source explicitly said no borough) and one
representing `Missing / Not Provided` (source never returned the field).
Every fact row gets a valid, non-null foreign key: pointing at a real
borough, or at whichever of these two placeholder rows applies.

## Consequences
- No fact row ever has a null foreign key into `dim_location`. This
  avoids a well-known relational pitfall: NULLs behave inconsistently in
  joins, `GROUP BY`, and filters (e.g. `NOT IN` can silently drop rows
  when NULLs are present), so professional dimensional modeling (the
  Kimball methodology) generally avoids nullable FKs, using explicit
  "unknown member" placeholder rows instead — this ADR applies that
  standard technique.
- The real distinction found during exploration is preserved rather than
  erased: it remains possible later to tell "the source explicitly said
  no borough" apart from "the source never got that far for this row,"
  if that difference ever matters for analysis.
- Open follow-up (not blocking this decision): check whether missing-key
  rows correlate with recency, the way the geocoding/computed-region
  fields did in the sample-bias finding. If so, that would be further
  evidence supporting the `:updated_at` watermark design (ADR-0002) — it
  would mean borough, too, can be backfilled after a request is created.
- Two placeholder rows add minor complexity to `dim_location` compared to
  a single catch-all "Unknown" row, but the cost is trivial and the
  information is cheap to keep now, versus impossible to reconstruct
  later if it were collapsed away.
