#!/usr/bin/env python3
"""Safely switch TradeSvr partition primaries with ZooKeeper CAS and readiness evidence.

The command is dry-run by default. A switch writes one new READY assignment
with epoch+1, but EnforceReadiness keeps business traffic fenced on the target
until TradeSvr finishes recovery and emits TRADE_PARTITION_READY for that epoch.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys

try:
    from tests.md_cluster_transition_host import DockerZk, canonical
except ModuleNotFoundError:
    from md_cluster_transition_host import DockerZk, canonical


DEFAULT_ROOT = "/dc/cluster/tradesvr/partitions"
DEFAULT_NODES = {"TradeSvrA", "TradeSvrB"}
READY_LINE = re.compile(
    r"TRADE_PARTITION_READY node:(?P<node>[^,]+), partition:(?P<partition>P[0-9]{3}), "
    r"epoch:(?P<epoch>[0-9]+), committedStateSeq:(?P<seq>[0-9]+), locations:(?P<locations>[0-9]+)"
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def replica_nodes(row: dict) -> list[str]:
    values = row.get("replicas")
    if values is None:
        values = [row.get("replica")]
    return [str(value).strip() for value in values if value and str(value).strip()]


def validate_current(row: dict) -> None:
    partition = row.get("partitionId")
    if not isinstance(partition, str) or not re.fullmatch(r"P[0-9]{3}", partition):
        raise ValueError(f"invalid partitionId: {partition}")
    if row.get("state") not in ("READY", "ACTIVE"):
        raise ValueError(f"partition is not routable: {partition} state={row.get('state')}")
    if int(row.get("epoch", 0)) <= 0:
        raise ValueError(f"invalid epoch: {row}")
    if int(row.get("assignmentVersion", 0)) <= 0:
        raise ValueError(f"invalid assignmentVersion: {row}")
    if int(row.get("protocolVersion", 0)) < 3:
        raise ValueError(f"invalid protocolVersion: {row}")
    primary = row.get("primary")
    replicas = replica_nodes(row)
    if primary not in DEFAULT_NODES or not replicas:
        raise ValueError(f"invalid topology: {row}")
    if any(node not in DEFAULT_NODES for node in replicas):
        raise ValueError(f"unsupported replica: {row}")
    if primary in replicas:
        raise ValueError(f"primary/replica overlap: {row}")


def switch_assignment(current: dict, source: str, target: str) -> dict:
    validate_current(current)
    if source == target or source not in DEFAULT_NODES or target not in DEFAULT_NODES:
        raise ValueError("source and target must be distinct TradeSvrA/TradeSvrB nodes")
    if current.get("primary") != source:
        raise ValueError(
            f"{current.get('partitionId')} current primary is {current.get('primary')}, not {source}"
        )
    replicas = replica_nodes(current)
    if target not in replicas:
        raise ValueError(
            f"{current.get('partitionId')} target {target} is not a hot replica: replicas={replicas}"
        )

    desired = json.loads(canonical(current))
    desired["epoch"] = int(current["epoch"]) + 1
    desired["assignmentVersion"] = int(current.get("assignmentVersion", 0)) + 1
    desired["primary"] = target
    desired["replica"] = source
    desired["replicas"] = [source]
    desired["learners"] = [
        node for node in (current.get("learners") or [])
        if node not in (source, target)
    ]
    # Trade lifecycle only examines routable assignments. Safety comes from the
    # process-local PartitionReadinessGuard enforced by PartitionServerGuard.
    desired["state"] = "READY"
    validate_current(desired)
    return desired


def parse_ready_evidence(text: str) -> set[tuple[str, str, int]]:
    result: set[tuple[str, str, int]] = set()
    for match in READY_LINE.finditer(text):
        result.add(
            (
                match.group("node").strip(),
                match.group("partition"),
                int(match.group("epoch")),
            )
        )
    return result


def save_plan(path: str, records: list[dict], source: str, target: str, root: str) -> None:
    value = {
        "schemaVersion": 1,
        "operation": "trade-primary-switch",
        "createdAt": utc_now(),
        "partitionRoot": root,
        "source": source,
        "target": target,
        "records": records,
    }
    with open(path, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def load_plan(path: str) -> dict:
    with open(path, encoding="utf-8") as stream:
        value = json.load(stream)
    if value.get("operation") != "trade-primary-switch":
        raise ValueError("plan operation is not trade-primary-switch")
    return value


def command_switch(args, zk: DockerZk) -> None:
    if args.apply and args.confirm_root != args.partition_root:
        raise ValueError("--apply requires --confirm-root to exactly match --partition-root")

    all_rows = zk.read_all(args.partitions)
    by_id = {record["partitionId"]: record for record in all_rows}
    selected = [
        partition_id for partition_id in sorted(by_id)
        if by_id[partition_id]["value"].get("primary") == args.from_node
    ]
    if args.partition:
        requested = set(args.partition)
        selected = [partition_id for partition_id in selected if partition_id in requested]
        if set(selected) != requested:
            raise ValueError("a requested partition is not currently primary on the source node")
    selected = selected[: args.limit]
    if not selected:
        raise ValueError("no source-primary Trade partitions selected")

    records = []
    for partition_id in selected:
        snapshot = by_id[partition_id]
        desired = switch_assignment(snapshot["value"], args.from_node, args.to_node)
        records.append({**snapshot, "desired": desired})

    save_plan(args.plan, records, args.from_node, args.to_node, args.partition_root)
    print(
        f"plan={args.plan} changes={len(records)} source={args.from_node} "
        f"target={args.to_node} apply={str(args.apply).lower()}"
    )
    if not args.apply:
        print("dry_run=true; inspect the plan before applying")
        return

    if args.batch_size <= 0:
        raise ValueError("batch size must be positive")
    for offset in range(0, len(records), args.batch_size):
        batch = records[offset : offset + args.batch_size]
        zk.cas_many(batch)
        print(
            f"applied={offset + len(batch)}/{len(records)} "
            f"partitions={batch[0]['partitionId']}..{batch[-1]['partitionId']}",
            flush=True,
        )
    print("assignment_switch=APPLIED readiness=PENDING")


def command_verify(args, zk: DockerZk) -> None:
    plan = load_plan(args.plan)
    if plan.get("partitionRoot") != args.partition_root:
        raise ValueError("plan partition root does not match requested root")
    if args.target_node and args.target_node != plan.get("target"):
        raise ValueError("target node does not match plan")

    target = str(plan["target"])
    evidence = parse_ready_evidence(zk.logs(args.target_container, plan["createdAt"]))
    missing = []

    for record in plan["records"]:
        current = zk.read(record["partitionId"])
        desired = record["desired"]
        if canonical(current["value"]) != canonical(desired):
            raise RuntimeError(f"assignment changed after switch: {record['partitionId']}")
        key = (target, record["partitionId"], int(desired["epoch"]))
        if key not in evidence:
            missing.append(record["partitionId"])

    if missing:
        raise RuntimeError(
            "target has not emitted TRADE_PARTITION_READY for: " + ",".join(missing[:20])
        )
    print(
        f"readiness=PASS target={target} partitions={len(plan['records'])} "
        f"assignment_and_epoch=verified"
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    result.add_argument("--zk-container", default="dc-saas-zookeeper")
    result.add_argument("--zk-server", default="127.0.0.1:32181")
    result.add_argument("--partition-root", default=DEFAULT_ROOT)
    result.add_argument("--partitions", type=int, default=256)
    result.add_argument("--docker-bin", default="docker")

    sub = result.add_subparsers(dest="command", required=True)

    switch = sub.add_parser("switch-primary")
    switch.add_argument("--from-node", required=True, choices=sorted(DEFAULT_NODES))
    switch.add_argument("--to-node", required=True, choices=sorted(DEFAULT_NODES))
    switch.add_argument("--partition", action="append")
    switch.add_argument("--limit", type=int, default=1)
    switch.add_argument("--batch-size", type=int, default=1)
    switch.add_argument("--plan", required=True)
    switch.add_argument("--apply", action="store_true")
    switch.add_argument("--confirm-root")

    verify = sub.add_parser("verify-ready")
    verify.add_argument("--plan", required=True)
    verify.add_argument("--target-node", choices=sorted(DEFAULT_NODES))
    verify.add_argument("--target-container", required=True)

    return result


def main(argv=None) -> None:
    args = parser().parse_args(argv)
    zk = DockerZk(args.zk_container, args.zk_server, args.partition_root, args.docker_bin)
    if args.command == "switch-primary":
        command_switch(args, zk)
    else:
        command_verify(args, zk)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
