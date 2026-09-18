#!/usr/bin/env python3
"""Build deterministic TradeSvr A/B assignments for the 256 location partitions."""

from __future__ import annotations

import json
from typing import Iterable


def build_initial_assignments(
    partition_count: int = 256,
    node_a: str = "TradeSvrA",
    node_b: str = "TradeSvrB",
) -> list[dict]:
    if partition_count <= 0:
        raise ValueError("partition_count must be positive")
    if not node_a or not node_b or node_a == node_b:
        raise ValueError("two distinct TradeSvr nodes are required")

    midpoint = partition_count // 2
    rows: list[dict] = []
    for index in range(partition_count):
        primary, replica = (node_a, node_b) if index < midpoint else (node_b, node_a)
        rows.append(
            {
                "partitionId": f"P{index:03d}",
                "epoch": 1,
                "assignmentVersion": 1,
                "protocolVersion": 3,
                "primary": primary,
                "replica": replica,
                "replicas": [replica],
                "learners": [],
                "placementGroup": "",
                "nodePool": "trade-ab",
                "state": "READY",
            }
        )
    return rows


def validate(rows: Iterable[dict], expected: int = 256) -> None:
    values = list(rows)
    if len(values) != expected:
        raise ValueError(f"expected {expected} assignments, got {len(values)}")

    expected_ids = {f"P{index:03d}" for index in range(expected)}
    actual_ids = {row.get("partitionId") for row in values}
    if actual_ids != expected_ids:
        raise ValueError("assignment set does not match expected Trade partitions")

    for row in values:
        if row.get("state") != "READY":
            raise ValueError(f"partition is not READY: {row.get('partitionId')}")
        if int(row.get("epoch", 0)) <= 0:
            raise ValueError(f"invalid epoch: {row}")
        if int(row.get("assignmentVersion", 0)) <= 0:
            raise ValueError(f"invalid assignmentVersion: {row}")
        if int(row.get("protocolVersion", 0)) < 3:
            raise ValueError(f"invalid protocolVersion: {row}")
        primary = row.get("primary")
        replicas = row.get("replicas") or [row.get("replica")]
        if primary not in {"TradeSvrA", "TradeSvrB"}:
            raise ValueError(f"invalid primary: {row}")
        if len(replicas) != 1 or replicas[0] not in {"TradeSvrA", "TradeSvrB"}:
            raise ValueError(f"invalid replica set: {row}")
        if primary == replicas[0]:
            raise ValueError(f"primary/replica overlap: {row}")


def write_jsonl(path: str, rows: Iterable[dict]) -> None:
    values = list(rows)
    validate(values, len(values))
    with open(path, "w", encoding="utf-8", newline="\n") as stream:
        for row in values:
            stream.write(json.dumps(row, separators=(",", ":"), sort_keys=True))
            stream.write("\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--partition-count", type=int, default=256)
    args = parser.parse_args()

    assignments = build_initial_assignments(args.partition_count)
    validate(assignments, args.partition_count)
    write_jsonl(args.output, assignments)
