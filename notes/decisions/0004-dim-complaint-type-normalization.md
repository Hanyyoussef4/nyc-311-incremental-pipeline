# ADR-0004: dim_complaint_type — normalize casing/whitespace to a single canonical label

## Status
Accepted

## Context
Data exploration found 276 distinct raw `complaint_type` values. After
normalizing case and whitespace (lowercase + strip), only 261 true
categories remain — 15 categories exist as duplicate pairs differing only
in casing/whitespace (mostly HPD-related categories: appliance, asbestos,
door/window, electric, elevator, flooring/stairs, general, heat/hot water,
mold, outside building, paint/plaster, plumbing, safety, unsanitary
condition, water leak). See `notes/data_exploration.md`.

This is a different situation from ADR-0003's `agency`/`DHS` case: there,
two genuinely different-sounding labels described the same agency, and a
rule was needed to choose which real-world wording should win. Here, there
is no separate "code" column, and the duplicates are not different
wording — they are the identical category typed with inconsistent
capitalization or stray whitespace (e.g. "PAINT/PLASTER" vs.
"Paint/Plaster"). There is nothing to vote on; both variants say the exact
same thing.

## Decision
`dim_complaint_type` will be keyed by a normalized identity —
`LOWER(TRIM(complaint_type))` — so that all casing/whitespace variants of
the same category collapse to one dimension row. The label shown to
people (the dimension's display value) will be produced by applying a
single, fixed formatting rule (e.g. Title Case) to that normalized key,
rather than picking whichever raw casing happened to appear most often in
the source data.

## Consequences
- All 15 known casing/whitespace duplicates collapse to their true 261
  categories. Because the fix is a normalization *rule* rather than a
  fixed list, any future variant Socrata introduces (not just the 15 seen
  today) is caught automatically, with no manual list or frequency
  counting to maintain.
- Reporting/grouping by `complaint_type` becomes reliable — counting
  "PAINT/PLASTER" complaints correctly includes every casing variant as
  one category, instead of silently splitting the count across two rows.
- Display labels reflect one consistent house style rather than whichever
  casing happened to be most common in the raw data — a deliberate
  trade-off of predictability over "the exact wording most rows used."
- Deliberately different approach from ADR-0003's majority-vote rule:
  majority-vote is the right tool when labels genuinely differ in content
  (DHS: two different phrases for one agency); a fixed normalization rule
  is the right tool when labels are the same content typed inconsistently
  (complaint_type: pure case/whitespace noise). The two ADRs together are
  a useful before/after for recognizing which situation you're in.
- The original raw `complaint_type` text is preserved as-is in the
  raw/staging layer — normalization only happens when building the
  dimension table, so no source data is lost or altered upstream.
