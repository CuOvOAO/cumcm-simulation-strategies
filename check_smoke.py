"""Fail CI if the demo crashes or fails the smoke case."""
import csv
import sys
with open(sys.argv[1], encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))
if not rows or any(r["status"] != "ok" or float(r["cleared_fraction"]) != 1 for r in rows):
    raise SystemExit("Smoke case failed")
print("Smoke case passed")
