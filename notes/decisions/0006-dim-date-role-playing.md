# ADR-0006: dim_date — single role-playing dimension, bounded range with an invalid-date placeholder

## Status
Accepted

## Context
The dataset carries several distinct date/timestamp fields that matter for
different reasons: `created_date` (when a request was filed, set once),
`closed_date` (when it reached Closed status, populated only once closed),
and `resolution_action_updated_date` (a more general "last resolution
activity" timestamp that can change even before a request is closed).
The `:updated_at` system field is different in kind from these three — it
is pipeline metadata (the incremental watermark from ADR-0002), not a
business-meaningful date for reporting, and is intentionally excluded from
this dimension.

Separately, initial data profiling (see the original project plan) found
implausible dates in the raw data — a max `closed_date` of 2033 and a max
`resolution_action_updated_date` in December 2026 — flagged at the time as
"good cleaning material" but not yet acted on.

This fact table's grain is one row per `unique_key`, holding only the
current state (ADR-0001) — this ADR is not about reconstructing status
history; it is about how to let people query the three business date
fields that already exist on that current-state row.

## Decision
Build a single `dim_date` table, one row per calendar day, covering a
deliberately bounded, plausible range (e.g. roughly a decade back through
a couple of years into the future) rather than every date value that
happens to appear in the raw data. The fact table will reference this one
table three times, through three separate foreign key columns —
`created_date_key`, `closed_date_key`, and
`resolution_action_updated_date_key` — a "role-playing dimension," the
standard technique for using one calendar table in more than one role.

Any fact row carrying a date outside `dim_date`'s bounded range (such as
the 2033 `closed_date`) will not match a real calendar day. Instead it
will link to an explicit "Invalid / Out-of-range Date" placeholder row in
`dim_date`, using the same technique as the borough placeholders in
ADR-0005, rather than a null foreign key or a silently-accepted bad date.

## Consequences
- One shared calendar table serves all three business date fields — "how
  many requests were filed in March" and "how many were closed in March"
  both become simple joins through different foreign key columns on the
  same underlying `dim_date` rows, with no duplicated calendar data.
- Known bad dates (like the 2033 `closed_date`) become a visible, countable
  data quality signal — they land on the placeholder row instead of
  silently polluting a real calendar month, and instead of crashing the
  pipeline over one bad field on one row. This feeds directly into the
  step 6 data quality checks planned later.
- `:updated_at` is deliberately not modeled through `dim_date` — it remains
  purely pipeline control metadata (ADR-0002's watermark), not a
  reporting dimension.
- The exact bounded date range, and the concrete mechanics of building and
  joining `dim_date`, are deferred to step 5 (star schema implementation),
  where they will be walked through hands-on with real `CREATE TABLE`
  statements and sample data rather than reasoned about in the abstract.
