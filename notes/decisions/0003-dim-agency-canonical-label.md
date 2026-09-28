# ADR-0003: dim_agency canonical label — majority-vote per agency code

## Status
Accepted

## Context
Data exploration found that `agency` codes do not map 1:1 to `agency_name`
labels in the raw source: 21 distinct `agency` codes but 22 distinct
`(agency, agency_name)` pairs. The mismatch was traced to a single
exception — `DHS` appears with two different `agency_name` values:
"Department of Homeless Services" (298,353 rows) and "Operations Unit -
Department of Homeless Services" (28 rows). All other 20 codes map
cleanly to exactly one label (see `notes/data_exploration.md`).

A dimension table's core promise is "one code = one row = one
consistent label." Without a rule for resolving this kind of
inconsistency, `dim_agency` would either duplicate DHS into two rows
(breaking that promise) or require someone to manually notice and fix
every future case like it.

## Decision
`dim_agency` will be keyed by the `agency` code, with exactly one row per
code. Where a code has more than one observed `agency_name` label, the
label used by the largest number of source rows for that code becomes
the dimension's canonical `agency_name` — the less common label(s) are
dropped from the dimension but the underlying fact rows are not lost;
they are simply linked to the winning label's dimension row.

For `DHS`, "Department of Homeless Services" wins (298,353 vs. 28 rows)
and becomes the sole canonical name.

## Consequences
- `dim_agency` stays a clean, one-row-per-code lookup table, which is
  what makes grouping/reporting by agency reliable (e.g. "all DHS
  requests" reliably means one thing).
- The rule is automatic and requires no manual maintenance: if a future
  data refresh introduces a new code with multiple labels, the same
  majority-vote logic resolves it without anyone having to notice and
  hand-fix it.
- Trade-off: the pipeline trusts frequency as the deciding signal, not
  which label "looks more official." In this case that happens to agree
  with intuition (the plain agency name beats an internal sub-unit
  label), but that won't always be guaranteed for future exceptions.
- No source data is discarded — every fact row (including the 28
  "Operations Unit" rows) is still loaded and still linked to `dim_agency`,
  just under the canonical label rather than its own original wording.
- This decision is specific to `agency`/`agency_name`, but the same
  majority-vote pattern is a reasonable default for other dimensions that
  turn out to have similar code-to-label inconsistencies, should any be
  found later.
