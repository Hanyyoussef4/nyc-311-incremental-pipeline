# NYC 311 Data Exploration Notes

Findings from exploring the NYC 311 Service Requests dataset (Socrata `erm2-nwe9`) on branch `feature/data-exploration`. These findings inform the schema design and incremental-load strategy for the pipeline.

## :updated_at filter test (2026-09-22)

Tested whether Socrata's system field `:updated_at` can be used to filter
for incremental loading.

- Unfiltered total count: 22,542,090
- `$where :updated_at > 2030-01-01` (future, control case): 0
- `$where :updated_at > 2020-01-01`: 22,550,280
- `$where :updated_at > 2026-09-14` (last week): 667,091

**Conclusion:** `:updated_at` filtering works and returns granular,
proportional results (control case correctly returned 0; last-week filter
returned a plausible ~3% of the dataset). This confirms the field can be
used as the watermark for incremental loads.

**Open note:** the "since 2020" count (22,550,280) is slightly higher than
the unfiltered total (22,542,090) taken a few minutes earlier — likely
explained by the live dataset growing between the two checks, not a filter
bug, since the filter's own control case (future date -> 0) and realistic
case (last week -> small % of total) both behaved correctly.

## Null pattern, duplicate check, and value consistency (2026-09-27)

### Null pattern (500-row sample, sorted by created_date DESC)

Ran `df.isnull().sum()` on a 500-row recent sample. Core required fields
(`unique_key`, `created_date`, `agency`, `agency_name`, `complaint_type`,
`descriptor`, `status`, `community_board`, `police_precinct`, `borough`,
`open_data_channel_type`, `park_facility_name`, `park_borough`) had zero
nulls. ~15 other fields were partially or heavily null (e.g.
`bridge_highway_name` 499/500, `taxi_company_borough` 499/500,
`taxi_pick_up_location` 491/500, `vehicle_type` 472/500, `facility_type`
489/500) — these are conditional fields, only populated for specific
complaint types (e.g. bridge/highway or taxi complaints), not a data
quality problem.

**Caveat:** these counts are scoped only to this 500-row sample, not the
full dataset — useful for spotting the core-vs-conditional pattern, not
for quantifying dataset-wide null rates.

### unique_key duplicate check (full dataset, ~22.5M rows)

Ran a server-side SoQL query (`$select unique_key, count(*)`, `$group
unique_key`, `$having count(*) > 1`, no `$where`/`$limit`) against the
entire dataset. Result: empty — zero `unique_key` values appear more than
once anywhere in the full table.

**Conclusion:** `unique_key` is confirmed as a true primary key across the
whole dataset. Fact table grain = one row per `unique_key`.

### agency / agency_name consistency (full dataset)

- 21 distinct `agency` codes; 22 distinct `agency_name` values; 22 distinct
  `(agency, agency_name)` pairs.
- Verification method: compare count of distinct codes (21) vs. count of
  distinct pairs (22) — a mismatch means at least one code maps to more
  than one name.
- Exception found: `DHS` maps to two labels — "Department of Homeless
  Services" (298,353 rows) and "Operations Unit - Department of Homeless
  Services" (28 rows). All other 20 codes map 1:1 to a single name.

**Design note:** decide during schema design whether `dim_agency` treats
these as one canonical row or two.

### status values (full dataset)

8 distinct values: Assigned (24,471), Cancel (1), Closed (22,144,165), In
Progress (283,260), Open (83,040), Pending (63,269), Started (4,848),
Unspecified (2,828). No casing/spelling inconsistencies. `Closed` accounts
for ~98% of all rows (expected for a multi-year dataset). `Cancel`
(count=1) and `Unspecified` are legitimate rare values, not typos.

**Design note:** a future data quality rule — "if status = Closed,
closed_date should not be null" — connects this to the null check above.

### borough values (full dataset)

7 groups returned: BRONX (4,807,044), BROOKLYN (6,782,654), MANHATTAN
(4,548,889), QUEENS (5,438,306), STATEN ISLAND (949,725), Unspecified
(40,831), and 38,433 rows where the `borough` key is missing entirely from
the API response (distinct from the literal `Unspecified` string value).

**Finding:** Socrata omits keys for empty fields rather than returning
`null` — `row['borough']` raises `KeyError` on some rows; `row.get(...)`
is needed. This also explains why pandas' `.isnull()` counts (above)
picked up nulls on other fields — pandas fills a missing key with `NaN`
automatically when building a DataFrame from a list of dicts with
inconsistent keys.

**Design note:** decide whether "missing borough" and "Unspecified" stay
distinct or get collapsed during schema design.

### complaint_type cardinality and value consistency (full dataset)

276 distinct raw `complaint_type` values. After normalizing (lowercase +
strip whitespace), only 261 distinct values remain — 15 categories exist
as duplicate pairs differing only in casing/whitespace (appear to be
HPD-related categories: appliance, asbestos, door/window, electric,
elevator, flooring/stairs, general, heat/hot water, mold, outside
building, paint/plaster, plumbing, safety, unsanitary condition, water
leak).

**Conclusion:** `complaint_type` needs a normalization step (case/
whitespace cleanup, or a mapping table) before it becomes a clean
dimension table. Not fixed now — noted for the transform/cleaning step.

### Sample bias discovery: geocoding/computed-region processing lag

Ran a query with `$select: '*'` and no `$where`/`$limit`/`$order`
(Socrata's default `$limit` of 1000 applied, in an unspecified row order).
This surfaced fields that never appeared at all in the earlier 500-row,
`created_date DESC`-sorted sample: `road_ramp` (998/1000 null, a
genuinely rare field) and four `:@computed_region_*` fields (only 13/1000
null each — ~98.7% populated).

**Key finding:** those four computed-region fields have the *same* null
count (13) as `latitude`, `longitude`, `location`,
`x_coordinate_state_plane`, and `y_coordinate_state_plane` in this batch —
strong evidence the computed-region fields are derived from lat/long via a
spatial lookup, and are null exactly when lat/long is null.

**Why they were invisible in the earlier sample:** pandas only creates a
DataFrame column for a key if at least one row in the sample has that key.
Zero of the 500 most-recent rows had any value for these fields, so the
columns didn't exist in that DataFrame at all — not "0 nulls," simply
absent. This means a `created_date`-sorted recency sample under-represents
fields that get filled in via a delayed backend process (geocoding), since
the very newest requests haven't been through that process yet.

**Why this matters for the pipeline:** this is a concrete, real example of
why the `:updated_at` watermark (not just `created_date`) is essential —
lat/long and computed-region fields likely arrive null at creation and get
backfilled via a later update, which only an `:updated_at`-based
incremental load will catch.

**Caveat:** no `$order` was specified for this query, so row order (and
thus which 1000 rows were returned) is Socrata's unspecified default —
not random, not guaranteed representative.
