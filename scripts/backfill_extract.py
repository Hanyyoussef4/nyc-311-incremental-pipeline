import os
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv()

APP_TOKEN = os.getenv("NYC_311_APP_TOKEN")
BASE_URL = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"

headers = {"X-App-Token": APP_TOKEN}

output_path = "raw_data/nyc311_backfill_2025-10-01_v2.jsonl"

WINDOW = "created_date >= '2025-10-01T00:00:00' AND created_date < '2026-10-01T00:00:00'"

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5

last_created_date = None
last_unique_key = None
total_rows = 0

if os.path.exists(output_path):
    with open(output_path, "r") as f:
        last_line = None
        for line in f:
            total_rows += 1
            last_line = line
    if last_line:
        last_row = json.loads(last_line)
        last_created_date = last_row["created_date"]
        last_unique_key = last_row["unique_key"]

if last_created_date:
    print(f"Resuming after created_date={last_created_date}, unique_key={last_unique_key} ({total_rows} rows so far)")
    where_clause = (
        f"{WINDOW} AND ((created_date > '{last_created_date}') OR "
        f"(created_date = '{last_created_date}' AND unique_key > '{last_unique_key}'))"
    )
else:
    print("Starting from the beginning")
    where_clause = WINDOW

params = {
    "$select": ":*,*",
    "$where": where_clause,
    "$limit": 20000,
    "$order": "created_date, unique_key"
}

page = 0

with open(output_path, "a") as f:
    while True:
        data = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = requests.get(BASE_URL, headers=headers, params=params, timeout=120)
                response.raise_for_status()
                data = response.json()
                break
            except requests.exceptions.RequestException as e:
                print(f"Attempt {attempt}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS)
                else:
                    print("Max retries reached. Giving up on this run.")
                    raise

        if not data:
            break

        for row in data:
            f.write(json.dumps(row) + "\n")

        rows_this_page = len(data)
        total_rows += rows_this_page
        page += 1

        last_row = data[-1]
        last_created_date = last_row["created_date"]
        last_unique_key = last_row["unique_key"]

        params["$where"] = (
            f"{WINDOW} AND ((created_date > '{last_created_date}') OR "
            f"(created_date = '{last_created_date}' AND unique_key > '{last_unique_key}'))"
        )

        print(f"page {page}: {rows_this_page} rows (running total: {total_rows})")

        if rows_this_page < params["$limit"]:
            break

print("Done. Total rows written:", total_rows)