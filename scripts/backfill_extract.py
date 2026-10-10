import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

APP_TOKEN = os.getenv("NYC_311_APP_TOKEN")
BASE_URL = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"

headers = {"X-App-Token": APP_TOKEN}

output_path = "raw_data/nyc311_backfill_2025-10-01.jsonl"

if os.path.exists(output_path):
    with open(output_path, "r") as f:
        offset = sum(1 for _ in f)
else:
    offset = 0

print(f"Resuming from offset {offset}")

params = {
    "$select": "*",
    "$where": "created_date >= '2025-10-01T00:00:00' AND created_date < '2026-10-01T00:00:00'",
    "$limit": 20000,
    "$offset": offset,
    "$order": "created_date, unique_key"
}

total_rows = offset
page = 0

with open(output_path, "a") as f:
    while True:
        params["$offset"] = offset
        response = requests.get(BASE_URL, headers=headers, params=params, timeout=120)
        data = response.json()

        if not data:
            break

        for row in data:
            f.write(json.dumps(row) + "\n")

        rows_this_page = len(data)
        total_rows += rows_this_page
        offset += rows_this_page
        page += 1

        print(f"page {page}: {rows_this_page} rows (running total: {total_rows})")

        if rows_this_page < params["$limit"]:
            break

print("Done. Total rows written:", total_rows)