#!/usr/bin/env python3
"""Safely bootstrap the initial TradeSvr A/B partition assignments in ZooKeeper."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from md_cluster_transition_host import DockerZk, canonical
from trade_cluster_assignments import build_initial_assignments, validate


DEFAULT_ROOT = "/dc/cluster/tradesvr/partitions"
DEFAULT_CONTAINER = "dc-saas-zookeeper"
DEFAULT_SERVER = "127.0.0.1:32181"


def run_cli(docker: str, container: str, server: str, commands: str, timeout: int = 60) -> str:
    result = subprocess.run(
        [docker, "exec", "-i", container, "zkCli.sh", "-server", server],
        input=commands + "\nquit\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout[-1500:])
    return result.stdout


def ensure_path(docker: str, container: str, server: str, path: str) -> None:
    current = ""
    for part in [item for item in path.split("/") if item]:
        current += "/" + part
        result = subprocess.run(
            [docker, "exec", "-i", container, "zkCli.sh", "-server", server],
            input=f'create {current} ""\nquit\n',
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, check=False,
        )
        output = result.stdout
        if result.returncode != 0 and "Node already exists:" not in output and "NodeExists" not in output:
            raise RuntimeError(f"failed to create {current}: {output[-1200:]}")
        if "KeeperErrorCode" in output and "NodeExists" not in output and "Node already exists:" not in output:
            raise RuntimeError(f"failed to create {current}: {output[-1200:]}")


def list_children(docker: str, container: str, server: str, path: str) -> list[str]:
    output = run_cli(docker, container, server, f"ls {path}")
    if "KeeperErrorCode" in output:
        raise RuntimeError(f"failed to list {path}: {output[-1200:]}")
    matches = re.findall(r"^\[([^\]]*)\]\s*$", output, re.MULTILINE)
    if not matches:
        return []
    text = matches[-1].strip()
    return [] if not text else [item.strip() for item in text.split(",") if item.strip()]


def save_plan(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, separators=(",", ":"), sort_keys=True))
            stream.write("\n")


def verify_exact(zk: DockerZk, rows: list[dict]) -> None:
    actual = zk.read_many(row["partitionId"] for row in rows)
    actual_by_id = {item["partitionId"]: item["value"] for item in actual}
    for row in rows:
        current = actual_by_id.get(row["partitionId"])
        if current is None or canonical(current) != canonical(row):
            raise RuntimeError(f"assignment verification mismatch: {row['partitionId']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-root")
    parser.add_argument("--partition-root", default=DEFAULT_ROOT)
    parser.add_argument("--partitions", type=int, default=256)
    parser.add_argument("--zk-container", default=DEFAULT_CONTAINER)
    parser.add_argument("--zk-server", default=DEFAULT_SERVER)
    parser.add_argument("--docker-bin", default="docker")
    parser.add_argument(
        "--plan",
        default="/data/dc-saas-runtime/evidence/trade-cluster-initial-assignments.jsonl",
    )
    args = parser.parse_args()

    rows = build_initial_assignments(args.partitions)
    validate(rows, args.partitions)
    save_plan(Path(args.plan), rows)

    print(
        f"plan={args.plan} partitions={len(rows)} "
        f"primaryA={sum(row['primary'] == 'TradeSvrA' for row in rows)} "
        f"primaryB={sum(row['primary'] == 'TradeSvrB' for row in rows)}"
    )
    if not args.apply:
        print("dry_run=true; pass --apply with exact --confirm-root to write ZooKeeper")
        return

    if args.confirm_root != args.partition_root:
        raise SystemExit("--apply requires --confirm-root to exactly match --partition-root")

    ensure_path(args.docker_bin, args.zk_container, args.zk_server, args.partition_root)
    children = list_children(args.docker_bin, args.zk_container, args.zk_server, args.partition_root)
    expected_ids = [row["partitionId"] for row in rows]

    zk = DockerZk(args.zk_container, args.zk_server, args.partition_root, args.docker_bin)
    if children:
        if sorted(children) != expected_ids:
            raise SystemExit(
                f"refusing bootstrap: partition root is not empty/exact; children={len(children)}"
            )
        verify_exact(zk, rows)
        print("bootstrap=already_exact verification=PASS")
        return

    commands = "\n".join(
        f"create {args.partition_root}/{row['partitionId']} {canonical(row)}" for row in rows
    )
    output = run_cli(args.docker_bin, args.zk_container, args.zk_server, commands, timeout=120)
    if "KeeperErrorCode" in output or "Exception" in output:
        raise RuntimeError(f"Trade assignment bootstrap failed: {output[-1600:]}")

    verify_exact(zk, rows)
    print("bootstrap=created verification=PASS")


if __name__ == "__main__":
    main()
