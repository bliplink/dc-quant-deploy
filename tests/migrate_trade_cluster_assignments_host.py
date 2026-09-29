#!/usr/bin/env python3
"""Migrate legacy TradeSvr ZooKeeper assignments to the protocol-v3 metadata shape.

Dry-run is the default. Applying requires --apply plus an exact --confirm-root.
The migration never changes partitionId, epoch, primary, effective replica, or state.
Writes use ZooKeeper data-version CAS and are verified after each batch.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

try:
    from tests.md_cluster_transition_host import DockerZk, canonical
    from tests.trade_cluster_assignments import validate
except ModuleNotFoundError:
    from md_cluster_transition_host import DockerZk, canonical
    from trade_cluster_assignments import validate

DEFAULT_ROOT = "/dc/cluster/tradesvr/partitions"
DEFAULT_NODES = {"TradeSvrA", "TradeSvrB"}


def effective_replica(row: dict) -> str:
    replicas = row.get("replicas")
    if replicas is None:
        replicas = [row.get("replica")]
    values = [str(value).strip() for value in replicas if value and str(value).strip()]
    if len(values) != 1:
        raise ValueError(f"expected exactly one Trade replica: {row}")
    replica = values[0]
    legacy_replica = row.get("replica")
    if legacy_replica and str(legacy_replica).strip() != replica:
        raise ValueError(f"replica/replicas disagree: {row}")
    return replica


def migrate_assignment(row: dict) -> dict:
    partition = row.get("partitionId")
    if not isinstance(partition, str) or len(partition) != 4 or not partition.startswith("P"):
        raise ValueError(f"invalid partitionId: {row}")
    if row.get("state") != "READY":
        raise ValueError(f"migration requires READY assignment: {row}")
    if int(row.get("epoch", 0)) <= 0:
        raise ValueError(f"invalid epoch: {row}")

    primary = row.get("primary")
    replica = effective_replica(row)
    if primary not in DEFAULT_NODES or replica not in DEFAULT_NODES or primary == replica:
        raise ValueError(f"invalid Trade topology: {row}")

    assignment_version = int(row.get("assignmentVersion", 0))
    protocol_version = int(row.get("protocolVersion", 0))
    if assignment_version < 0 or protocol_version < 0:
        raise ValueError(f"invalid version metadata: {row}")

    desired = json.loads(canonical(row))
    desired["assignmentVersion"] = assignment_version or 1
    desired["protocolVersion"] = protocol_version or 3
    if desired["protocolVersion"] < 3:
        desired["protocolVersion"] = 3
    desired["replica"] = replica
    desired["replicas"] = [replica]
    desired.setdefault("learners", [])
    desired.setdefault("placementGroup", "")
    desired.setdefault("nodePool", "trade-ab")

    for field in ("partitionId", "epoch", "primary", "state"):
        if desired.get(field) != row.get(field):
            raise ValueError(f"migration changed protected field {field}: {row}")
    if effective_replica(desired) != replica:
        raise ValueError(f"migration changed effective replica: {row}")
    return desired


def topology_counts(rows: list[dict]) -> tuple[Counter, Counter]:
    primary = Counter()
    replica = Counter()
    for row in rows:
        primary[row["primary"]] += 1
        replica[effective_replica(row)] += 1
    return primary, replica


def save_plan(path: str, records: list[dict]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "operation": "trade-assignment-v3-migration",
        "records": [
            {
                "partitionId": record["partitionId"],
                "zkVersion": record["version"],
                "before": record["value"],
                "after": record["desired"],
            }
            for record in records
        ],
    }
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--zk-container", default="dc-saas-zookeeper")
    parser.add_argument("--zk-server", default="127.0.0.1:32181")
    parser.add_argument("--partition-root", default=DEFAULT_ROOT)
    parser.add_argument("--partitions", type=int, default=256)
    parser.add_argument("--docker-bin", default="docker")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-root")
    args = parser.parse_args()

    if args.partitions <= 0 or args.batch_size <= 0:
        raise SystemExit("partitions and batch-size must be positive")
    if args.apply and args.confirm_root != args.partition_root:
        raise SystemExit("--apply requires --confirm-root to exactly match --partition-root")

    zk = DockerZk(
        args.zk_container, args.zk_server, args.partition_root, args.docker_bin
    )
    snapshots = zk.read_all(args.partitions)
    expected_ids = {f"P{index:03d}" for index in range(args.partitions)}
    actual_ids = {record["partitionId"] for record in snapshots}
    if actual_ids != expected_ids:
        raise RuntimeError("live Trade assignment set is incomplete")

    before_values = [record["value"] for record in snapshots]
    before_primary, before_replica = topology_counts(before_values)
    records = []
    for record in snapshots:
        desired = migrate_assignment(record["value"])
        if canonical(desired) != canonical(record["value"]):
            records.append({**record, "desired": desired})

    save_plan(args.plan, records)
    print(
        f"plan={args.plan} partitions={len(snapshots)} changes={len(records)} "
        f"primaryA={before_primary['TradeSvrA']} primaryB={before_primary['TradeSvrB']} "
        f"replicaA={before_replica['TradeSvrA']} replicaB={before_replica['TradeSvrB']}"
    )
    if not args.apply:
        print("dry_run=true; topology and epoch are unchanged by the planned migration")
        return

    for offset in range(0, len(records), args.batch_size):
        batch = records[offset : offset + args.batch_size]
        zk.cas_many(batch)
        print(
            f"applied={offset + len(batch)}/{len(records)} "
            f"partitions={batch[0]['partitionId']}..{batch[-1]['partitionId']}",
            flush=True,
        )

    after_records = zk.read_all(args.partitions)
    after_values = [record["value"] for record in after_records]
    validate(after_values, args.partitions)
    after_primary, after_replica = topology_counts(after_values)
    if before_primary != after_primary or before_replica != after_replica:
        raise RuntimeError("topology counts changed during metadata migration")

    before_by_id = {row["partitionId"]: row for row in before_values}
    for row in after_values:
        old = before_by_id[row["partitionId"]]
        for field in ("partitionId", "epoch", "primary", "state"):
            if row.get(field) != old.get(field):
                raise RuntimeError(
                    f"protected field changed for {row['partitionId']}: {field}"
                )
        if effective_replica(row) != effective_replica(old):
            raise RuntimeError(f"replica changed for {row['partitionId']}")

    print(
        f"migration=PASS partitions={len(after_values)} changes={len(records)} "
        f"primaryA={after_primary['TradeSvrA']} primaryB={after_primary['TradeSvrB']}"
    )


if __name__ == "__main__":
    main()
