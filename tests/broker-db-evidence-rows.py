#!/usr/bin/env python3
"""Validate run-specific Broker DB evidence after eventual Projection catchup.

Takes five COUNT(*) rows on stdin:
maker deposit, taker deposit, maker withdrawal,
maker execution exact ExecID, taker execution exact ExecID.

Exit 0 = PASS, 3 = WAIT (not yet persisted), 2 = FAIL (extra/invalid data).
Never emits customer IDs, credential fields or raw SQL.
"""
import sys


def classify(text):
    rows = [row.strip() for row in text.splitlines() if row.strip()]
    if len(rows) != 5 or any(not row.isdigit() for row in rows):
        return "FAIL"
    values = [int(row) for row in rows]
    if any(value > 1 for value in values):
        return "FAIL"
    return "PASS" if all(value == 1 for value in values) else "WAIT"


if __name__ == "__main__":
    status = classify(sys.stdin.read())
    print("BROKER_PROJECTION_" + status)
    raise SystemExit({"PASS": 0, "WAIT": 3, "FAIL": 2}[status])
