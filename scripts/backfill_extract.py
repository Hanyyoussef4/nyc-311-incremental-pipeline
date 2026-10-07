import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

APP_TOKEN = os.getenv("NYC_311_APP_TOKEN")
BASE_URL = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"

headers = {"X-App-Token": APP_TOKEN}

offset = 0

params = {
    "$select": "*",
    "$where": "created_date >= '2025-10-01T00:00:00'",
    "$limit": 20000,
    "$offset": offset,
    "$order": "created_date, unique_key"
}

output_path = "raw_data/nyc311_backfill_2025-10-01.jsonl"
total_rows = 0
page = 0

with open(output_path, "w") as f:
    while True:
        params["$offset"] = offset
        response = requests.get(BASE_URL, headers=headers, params=params)
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