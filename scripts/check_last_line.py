"""
Safety check to run BEFORE resuming backfill_extract.py (or any similarly
structured .jsonl pull).

Checks the very last line of the file (only looks at the end, never reads
the whole file - stays fast no matter how many GB it is) for two things:

  1. Is it valid JSON at all? (catches a line cut off mid-write by Ctrl+C)
  2. Does it have real, non-empty values for the two fields the resume
     logic actually depends on - unique_key and created_date? A row could
     be syntactically valid JSON and still be missing one of these, which
     would crash the resume logic even though the JSON itself parses fine.

If either check fails, that line isn't safe to resume from, so it's
removed - backfill_extract.py will then resume from the line before it.

Usage:
    python3 scripts/check_last_line.py raw_data/nyc311_backfill_2025-10-01_v2.jsonl
"""

import sys
import json
import os

if len(sys.argv) != 2:
    print("Usage: python3 scripts/check_last_line.py <path_to_jsonl_file>")
    sys.exit(1)

path = sys.argv[1]
CHUNK_SIZE = 65536  # 64 KB - comfortably bigger than one row

file_size = os.path.getsize(path)
read_start = max(0, file_size - CHUNK_SIZE)

with open(path, "rb") as f:
    f.seek(read_start)
    tail = f.read()

first_nl = tail.find(b"\n")
if first_nl == -1:
    print("File too short to check safely this way (fewer bytes than one chunk).")
    sys.exit(1)

clean_tail = tail[first_nl + 1:]
clean_tail_start = read_start + first_nl + 1

lines_with_offsets = []
offset = clean_tail_start
for raw_line in clean_tail.split(b"\n"):
    lines_with_offsets.append((offset, raw_line))
    offset += len(raw_line) + 1

while lines_with_offsets and not lines_with_offsets[-1][1].strip():
    lines_with_offsets.pop()

if not lines_with_offsets:
    print("No complete line found near the end of the file.")
    sys.exit(1)

last_offset, last_line = lines_with_offsets[-1]


def remove_last_line(reason):
    print(f"{reason} Removing it...")
    with open(path, "r+b") as f:
        f.truncate(last_offset)
    print("Removed. Safe to resume now - re-run backfill_extract.py.")
    sys.exit(0)


try:
    row = json.loads(last_line)
except json.JSONDecodeError:
    remove_last_line("Last line is INCOMPLETE (cut off mid-write).")

unique_key = row.get("unique_key")
created_date = row.get("created_date")

problems = []
if not unique_key:
    problems.append("missing/empty unique_key")
if not created_date:
    problems.append("missing/empty created_date")

if problems:
    remove_last_line(f"Last line parses as JSON but is unhealthy ({', '.join(problems)}).")
else:
    print("Last line is complete and healthy - safe to resume, no changes made.")
    print(f"  unique_key:   {unique_key}")
    print(f"  created_date: {created_date}")
