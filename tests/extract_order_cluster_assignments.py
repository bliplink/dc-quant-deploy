#!/usr/bin/env python3
"""Extract assignment JSON lines from noisy ZooKeeper CLI output.

ZooKeeper preserves the field order used by the last writer. Never assume
``partitionId`` is the first field of an assignment.
"""

import json
import sys


def extract(lines):
    for raw in lines:
        line = raw.strip()
        if not (line.startswith("{") and '"partitionId"' in line):
            continue
        value = json.loads(line)
        if not isinstance(value, dict) or not isinstance(value.get("partitionId"), str):
            raise ValueError("invalid Order partition assignment JSON")
        yield json.dumps(value, separators=(",", ":"), ensure_ascii=False)


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as source:
        for assignment in extract(source):
            print(assignment)
