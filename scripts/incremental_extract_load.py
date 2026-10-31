"""
Incremental extract/load for NYC 311 Service Requests.

Pulls complaints whose Socrata system field :updated_at falls inside a
window decided *before* any API call is made -- the same "fixed window,
decided upfront" principle the backfill used for created_date (see
notes/decisions/0002-watermark-strategy.md), applied here to :updated_at
instead.

One run's full lifecycle:
  1. Read control.pipeline_state.last_watermark -> watermark_start.
     Decide watermark_end = clock_timestamp() - WATERMARK_END_BUFFER_MINUTES,
     and INSERT a new RUNNING row into control.pipeline_runs with both
     boundaries, before any extraction happens. (Mirrors the manual INSERT
     run in DBeaver while this design was being worked out.)
  2. Pull from Socrata, filtered to that fixed window, via the same keyset
     (cursor) pagination + lightweight retry wrapper as backfill_extract.py
     -- just ordered by (:updated_at, unique_key) instead of
     (created_date, unique_key), since :updated_at is the thing bounding
     this window. Written to a fresh raw_data/*.jsonl file per run.
  3. Dedupe the extracted rows against staging on (unique_key, updated_at).
     The window above is deliberately wider than strictly necessary (the
     30-minute trailing buffer, and -- for this first run specifically --
     a watermark_start seeded well before the backfill's own cutoff) on
     purpose: re-pulling a row whose exact version is already staged is
     harmless and gets thrown away here; the thing we're protecting
     against is a version we DON'T already have, which this check would
     never throw away.
  4. Load whatever survives dedup into staging via COPY, same approach as
     load_staging.py -- same COLUMNS / JSON_COLUMNS / SOCRATA_KEY_OVERRIDES,
     since this also uses the :*,* select.
  5. On success: mark the pipeline_runs row SUCCESS (finish time, row
     counts) and advance pipeline_state.last_watermark to watermark_end.
     On any failure: mark the row FAILED and leave pipeline_state
     untouched, so the next attempt retries the exact same window from
     scratch rather than resuming mid-file -- unlike the backfill, a
     failed incremental run is cheap enough to just redo whole.

NOTE: this script always creates its OWN new row in control.pipeline_runs
(step 1). If a manual test row already exists there from working out the
control-table design by hand, delete it first so it doesn't sit forever
stuck on RUNNING.
"""

import os
import csv
import io
import json
import time
from datetime import datetime

import psycopg2
import requests
from dotenv import load_dotenv

load_dotenv()

APP_TOKEN = os.getenv("NYC_311_APP_TOKEN")
BASE_URL = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"
headers = {"X-App-Token": APP_TOKEN}

PIPELINE_NAME = "nyc311_incremental"
WATERMARK_END_BUFFER_MINUTES = 30
PAGE_LIMIT = 20000
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5

# Floor only, deliberately no ceiling: this pipeline should keep picking
# up newly-created complaints forever going forward (that's the whole
# point of it), but has no reason to surface updates to complaints from
# before the backfill's own start -- those have no history in staging
# at all, so a "new" row for one is more confusing than useful.
# Discovered after run 2 pulled 77,794 rows with created_date as far
# back as 2020-01-01, none of which belong in this dataset's scope.
SCOPE_CREATED_DATE_START = "2025-10-01T00:00:00"

RAW_DATA_DIR = "raw_data"

# Matches sql/001_create_staging_table.sql + sql/002_add_watermark_column.sql,
# column for column, EXCEPT _loaded_at (left out on purpose -- the table's
# own DEFAULT NOW() fills it in, same reasoning as load_staging.py).
COLUMNS = [
    "unique_key", "address_type", "agency", "agency_name", "complaint_type",
    "descriptor", "descriptor_2", "location_type", "incident_zip",
    "incident_address", "street_name", "cross_street_1", "cross_street_2",
    "intersection_street_1", "intersection_street_2", "city", "landmark",
    "facility_type", "status", "resolution_description", "community_board",
    "council_district", "police_precinct", "bbl", "borough",
    "x_coordinate_state_plane", "y_coordinate_state_plane",
    "open_data_channel_type", "park_facility_name", "park_borough",
    "vehicle_type", "taxi_company_borough", "taxi_pick_up_location",
    "bridge_highway_name", "bridge_highway_direction", "road_ramp",
    "bridge_highway_segment", "latitude", "longitude",
    "computed_region_f5dn_yrer", "computed_region_yeji_bk3q",
    "computed_region_sbqj_enih", "computed_region_92fq_4b7q",
    "created_date", "closed_date", "due_date",
    "resolution_action_updated_date", "location", "raw_payload",
    "_source_file", "updated_at",
]
JSON_COLUMNS = {"location", "raw_payload"}
SOCRATA_KEY_OVERRIDES = {
    "updated_at": ":updated_at",
    "computed_region_f5dn_yrer": ":@computed_region_f5dn_yrer",
    "computed_region_yeji_bk3q": ":@computed_region_yeji_bk3q",
    "computed_region_sbqj_enih": ":@computed_region_sbqj_enih",
    "computed_region_92fq_4b7q": ":@computed_region_92fq_4b7q",
}


def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def parse_socrata_timestamp(value):
    """Socrata's :updated_at comes back as e.g. '2025-12-26T17:24:15.863Z'.
    Python's datetime.fromisoformat doesn't accept a trailing 'Z' on the
    versions this project targets, so swap it for the equivalent explicit
    '+00:00' offset first. Returns a timezone-aware datetime, so it can be
    safely compared against what psycopg2 hands back for a TIMESTAMPTZ
    column -- comparing the raw strings instead would be a real bug, since
    Postgres won't necessarily echo the same 'Z' formatting back."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def start_run(conn):
    """Step 1: decide the window and log a RUNNING row *before* any
    extraction happens."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO control.pipeline_runs (pipeline_name, watermark_start, watermark_end)
            VALUES (
                %s,
                (SELECT last_watermark FROM control.pipeline_state WHERE pipeline_name = %s),
                clock_timestamp() - (%s * INTERVAL '1 minute')
            )
            RETURNING run_id, watermark_start, watermark_end;
            """,
            (PIPELINE_NAME, PIPELINE_NAME, WATERMARK_END_BUFFER_MINUTES),
        )
        run_id, watermark_start, watermark_end = cur.fetchone()
    conn.commit()
    return run_id, watermark_start, watermark_end


def fetch_page(params):
    """Same lightweight retry wrapper as backfill_extract.py."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(BASE_URL, headers=headers, params=params, timeout=120)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS)
            else:
                print("Max retries reached. Giving up on this run.")
                raise


def extract(watermark_start, watermark_end, output_path):
    """Step 2: keyset (cursor) pagination on (:updated_at, unique_key),
    bounded by the fixed window decided in step 1 -- same technique
    backfill_extract.py uses on (created_date, unique_key), for the same
    reason (offset-based pagination breaks when the underlying result set
    keeps changing while you page through it, which is exactly what's
    happening here since the source updates live)."""
    window = (
        f":updated_at > '{watermark_start.isoformat()}' "
        f"AND :updated_at <= '{watermark_end.isoformat()}' "
        f"AND created_date >= '{SCOPE_CREATED_DATE_START}'"
    )

    last_updated_at = None
    last_unique_key = None
    total_rows = 0
    page = 0

    where_clause = window

    with open(output_path, "w") as f:
        while True:
            params = {
                "$select": ":*,*",
                "$where": where_clause,
                "$limit": PAGE_LIMIT,
                "$order": ":updated_at, unique_key",
            }
            data = fetch_page(params)

            if not data:
                break

            for row in data:
                f.write(json.dumps(row) + "\n")

            rows_this_page = len(data)
            total_rows += rows_this_page
            page += 1

            last_row = data[-1]
            last_updated_at = last_row[":updated_at"]
            last_unique_key = last_row["unique_key"]

            where_clause = (
                f"{window} AND ((:updated_at > '{last_updated_at}') OR "
                f"(:updated_at = '{last_updated_at}' AND unique_key > '{last_unique_key}'))"
            )

            print(f"  page {page}: {rows_this_page} rows (running total: {total_rows})")

            if rows_this_page < PAGE_LIMIT:
                break

    return total_rows


def row_to_values(row, source_file):
    """Same mapping as load_staging.py -- see that file for the reasoning
    on JSON_COLUMNS / SOCRATA_KEY_OVERRIDES."""
    values = []
    for col in COLUMNS:
        if col == "raw_payload":
            values.append(json.dumps(row))
        elif col == "_source_file":
            values.append(source_file)
        elif col in JSON_COLUMNS:
            val = row.get(col)
            values.append(json.dumps(val) if val is not None else None)
        elif col in SOCRATA_KEY_OVERRIDES:
            values.append(row.get(SOCRATA_KEY_OVERRIDES[col]))
        else:
            values.append(row.get(col))
    return values


def dedupe_and_load(conn, raw_path, source_file):
    """Steps 3 + 4: drop anything whose exact (unique_key, updated_at)
    version is already in staging -- this is what makes the overlap in
    the window (the 30-minute buffer, and this run's generous
    watermark_start) safe rather than a source of duplicates -- then COPY
    whatever's left into staging."""
    with open(raw_path, "r") as f:
        extracted_rows = [json.loads(line) for line in f if line.strip()]

    rows_pulled = len(extracted_rows)
    if rows_pulled == 0:
        return 0, 0

    # Guard against the extraction itself containing an exact duplicate
    # (unique_key, updated_at) pair -- e.g. a retried page re-fetching rows
    # already written earlier in this same run. Keep the first occurrence
    # of each pair seen, in extraction order.
    seen_in_batch = set()
    deduped_rows = []
    for row in extracted_rows:
        pair = (row["unique_key"], row[":updated_at"])
        if pair in seen_in_batch:
            continue
        seen_in_batch.add(pair)
        deduped_rows.append(row)
    extracted_rows = deduped_rows

    unique_keys = list({row["unique_key"] for row in extracted_rows})

    # idx_staging_311_current (unique_key, _loaded_at DESC) still lets
    # Postgres jump straight to these keys even though it's not indexed on
    # updated_at -- unique_key is its leading column, and this run only
    # touches however many complaints actually changed, not the full table.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT unique_key, updated_at FROM staging.staging_311_requests "
            "WHERE unique_key = ANY(%s)",
            (unique_keys,),
        )
        already_have = {(uk, ts) for uk, ts in cur.fetchall()}

    new_rows = [
        row for row in extracted_rows
        if (row["unique_key"], parse_socrata_timestamp(row[":updated_at"])) not in already_have
    ]

    if new_rows:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        for row in new_rows:
            writer.writerow(row_to_values(row, source_file))
        buffer.seek(0)

        copy_sql = (
            f"COPY staging.staging_311_requests ({', '.join(COLUMNS)}) "
            "FROM STDIN WITH (FORMAT csv)"
        )
        with conn.cursor() as cur:
            cur.copy_expert(copy_sql, buffer)

    return rows_pulled, len(new_rows)


def finish_run(conn, run_id, status, rows_pulled=0, rows_inserted=0, notes=None, watermark_end=None):
    """Step 5: close out the run. Only on SUCCESS does pipeline_state's
    bookmark actually move -- on FAILED it's deliberately left untouched,
    so the next attempt retries the exact same window from scratch."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE control.pipeline_runs
            SET status = %s,
                run_finished_at = clock_timestamp(),
                rows_pulled = %s,
                rows_inserted = %s,
                notes = %s
            WHERE run_id = %s;
            """,
            (status, rows_pulled, rows_inserted, notes, run_id),
        )
        if status == "SUCCESS":
            cur.execute(
                """
                UPDATE control.pipeline_state
                SET last_watermark = %s,
                    last_updated_at = clock_timestamp()
                WHERE pipeline_name = %s;
                """,
                (watermark_end, PIPELINE_NAME),
            )
    conn.commit()


def main():
    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    conn = get_connection()
    run_id = None
    try:
        run_id, watermark_start, watermark_end = start_run(conn)
        print(f"Run {run_id} started. Window: ({watermark_start}, {watermark_end}]")

        source_file = f"nyc311_incremental_run{run_id}.jsonl"
        output_path = os.path.join(RAW_DATA_DIR, source_file)

        rows_pulled = extract(watermark_start, watermark_end, output_path)
        print(f"Extraction done: {rows_pulled:,} rows pulled from Socrata.")

        rows_pulled, rows_inserted = dedupe_and_load(conn, output_path, source_file)
        skipped = rows_pulled - rows_inserted
        print(f"Load done: {rows_inserted:,} new/changed rows appended "
              f"({skipped:,} already had this exact version staged, skipped).")

        finish_run(conn, run_id, "SUCCESS", rows_pulled, rows_inserted, watermark_end=watermark_end)
        print(f"Run {run_id} marked SUCCESS. pipeline_state advanced to {watermark_end}.")

    except Exception as e:
        print(f"Run failed: {e}")
        if run_id is not None:
            # A failure partway through (e.g. the COPY in dedupe_and_load)
            # can leave this connection's transaction aborted. Any further
            # command -- including the UPDATE below -- would fail with
            # InFailedSqlTransaction unless we roll back first.
            conn.rollback()
            finish_run(conn, run_id, "FAILED", notes=str(e)[:500])
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
