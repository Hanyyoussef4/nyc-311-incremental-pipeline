"""
Loads the backfilled raw_data/*.jsonl file into staging.staging_311_requests.

Design decisions (see notes/decisions/0007-staging-append-only-history.md
and sql/001_create_staging_table.sql for the full reasoning):
  - Uses Postgres COPY (not row-by-row INSERT) for bulk-load speed.
  - Reads and sends the file in chunks (to avoid loading 3.96M rows into
    memory at once), but the whole load runs as ONE transaction -- commit()
    is only called once, at the very end. This matters because Postgres's
    NOW() is pinned to the start of the transaction: as long as everything
    stays in one transaction, every row gets the exact same _loaded_at
    automatically, with no extra code needed. If this were split into
    multiple committed transactions, each chunk would get its own slightly
    different _loaded_at, which would be wrong for a single backfill load.
  - _loaded_at is intentionally left OUT of the explicit column list below,
    so the table's own `DEFAULT NOW()` fills it in -- see the paragraph
    above for why that's sufficient and correct here.
  - If the load fails partway through, the whole transaction rolls back
    automatically (nothing partial is left behind). This is a one-time
    script: on failure, just fix the issue and re-run it from scratch.

This version reads from the corrected re-pull (nyc311_backfill_2025-10-01_v2.jsonl),
extracted with $select=:*,* instead of the original $select=*, so it includes
:updated_at (the ADR-0002 watermark field, added to the table via
sql/002_add_updated_at_column.sql) and the system-field versions of the
computed_region_* columns (:@computed_region_... instead of the plain names
the original "*" select returned). See SOCRATA_KEY_OVERRIDES below.
"""

import os
import json
import csv
import io

import psycopg2
from dotenv import load_dotenv

load_dotenv()

INPUT_FILE = "raw_data/nyc311_backfill_2025-10-01_v2.jsonl"
CHUNK_SIZE = 50000

# Matches sql/001_create_staging_table.sql + sql/002_add_updated_at_column.sql,
# column for column, EXCEPT _loaded_at (left out on purpose -- see module
# docstring).
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

# These two columns hold JSON text (for the JSONB columns), not plain text.
JSON_COLUMNS = {"location", "raw_payload"}

# Columns whose value lives under a different key in the raw Socrata row than
# the column's own name. Needed because the :*,* select (used for this re-pull
# only, not the original one) renames a few fields:
#   - :updated_at is a system field, Socrata returns it with a leading colon
#   - the computed_region_* fields come back as :@computed_region_* under this
#     select, instead of the plain names the original "*" select used
SOCRATA_KEY_OVERRIDES = {
    "updated_at": ":updated_at",
    "computed_region_f5dn_yrer": ":@computed_region_f5dn_yrer",
    "computed_region_yeji_bk3q": ":@computed_region_yeji_bk3q",
    "computed_region_sbqj_enih": ":@computed_region_sbqj_enih",
    "computed_region_92fq_4b7q": ":@computed_region_92fq_4b7q",
}


def row_to_values(row, source_file):
    """Maps one parsed JSON row (a dict) to a list of values, in the exact
    order of COLUMNS above. Socrata omits keys with null/empty values
    entirely, so row.get(col) correctly returns None for any field that
    isn't present on this particular row -- that becomes a real NULL once
    written out as an empty CSV field."""
    values = []
    for col in COLUMNS:
        if col == "raw_payload":
            # The entire original row, untouched -- the safety net.
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


def build_csv_buffer(rows, source_file):
    """Builds an in-memory CSV buffer for one chunk of rows, in the format
    Postgres's COPY ... FORMAT csv expects. Python's csv.writer handles
    quoting/escaping automatically (commas, quotes, embedded newlines in
    free-text fields like resolution_description), and writes None as an
    empty, unquoted field -- which COPY FORMAT csv reads back as NULL."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in rows:
        writer.writerow(row_to_values(row, source_file))
    buffer.seek(0)
    return buffer


def main():
    source_file = os.path.basename(INPUT_FILE)

    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )

    try:
        with conn.cursor() as cur:
            # Safety check: warn if this file was already loaded, rather than
            # silently doubling the data (append-only won't block it -- the
            # primary key is (unique_key, _loaded_at), so a second run would
            # just succeed with a new timestamp).
            cur.execute(
                "SELECT COUNT(*) FROM staging.staging_311_requests "
                "WHERE _source_file = %s",
                (source_file,),
            )
            existing = cur.fetchone()[0]
            if existing > 0:
                print(f"Warning: {existing:,} rows already loaded from {source_file}.")
                confirm = input("Continue and load another copy anyway? [y/N] ")
                if confirm.strip().lower() != "y":
                    print("Aborted. No changes made.")
                    return

        total_loaded = 0
        chunk = []

        copy_sql = (
            f"COPY staging.staging_311_requests ({', '.join(COLUMNS)}) "
            "FROM STDIN WITH (FORMAT csv)"
        )

        with open(INPUT_FILE, "r") as f, conn.cursor() as cur:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                chunk.append(json.loads(line))

                if len(chunk) >= CHUNK_SIZE:
                    buffer = build_csv_buffer(chunk, source_file)
                    cur.copy_expert(copy_sql, buffer)
                    total_loaded += len(chunk)
                    print(f"Loaded {total_loaded:,} rows...")
                    chunk = []

            if chunk:
                # Final partial chunk, if any rows are left over.
                buffer = build_csv_buffer(chunk, source_file)
                cur.copy_expert(copy_sql, buffer)
                total_loaded += len(chunk)
                print(f"Loaded {total_loaded:,} rows...")

        # Only commit once, at the very end -- see module docstring for why.
        conn.commit()
        print(f"Done. Total rows loaded: {total_loaded:,}")

    except Exception as e:
        conn.rollback()
        print(f"Load failed, rolled back (no partial data left behind): {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
