#!/usr/bin/env python3
"""Drain one MDSvr primary node in bounded, readiness-gated CAS batches."""

import argparse
import json
import os
import sys
import time

try:
    from tests.md_cluster_assignment_plan import plan_primary_drain, validate
    from tests.md_cluster_transition_host import (
        DEFAULT_NODES,
        DEFAULT_ROOT,
        DockerZk,
        apply_records,
        canonical,
        load_jsonl,
        parse_ready_evidence,
        plan_records,
        require_route_evidence,
        save_plan,
    )
except ModuleNotFoundError:
    from md_cluster_assignment_plan import plan_primary_drain, validate
    from md_cluster_transition_host import (
        DEFAULT_NODES,
        DEFAULT_ROOT,
        DockerZk,
        apply_records,
        canonical,
        load_jsonl,
        parse_ready_evidence,
        plan_records,
        require_route_evidence,
        save_plan,
    )


def select_source_partitions(rows, source, limit):
    return [
        row["partitionId"]
        for row in sorted(rows, key=lambda item: item["partitionId"])
        if row.get("primary") == source
    ][:limit]


def ready_value(recovering):
    value = json.loads(canonical(recovering))
    if value.get("state") != "RECOVERING":
        raise ValueError("ready promotion requires RECOVERING input")
    value["state"] = "READY"
    value["assignmentVersion"] = int(value.get("assignmentVersion", 0)) + 1
    return value


def evidence_path(directory, source, target, batch, state):
    return os.path.join(
        directory,
        f"md-{source.lower()}-to-{target.lower()}-batch-{batch:03d}-{state}.json",
    )


def wait_primary_ready(zk, routes, assignments, target, selected, container, since, timeout):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        evidence = parse_ready_evidence(zk.logs(container, since))
        try:
            require_route_evidence(
                routes, assignments, target, "PRIMARY", evidence, 256, selected
            )
            return
        except RuntimeError as error:
            last_error = error
            time.sleep(2)
    raise RuntimeError(f"target primary readiness timed out: {last_error}")


def run(args):
    if args.source == args.target:
        raise ValueError("source and target must differ")
    if args.source not in DEFAULT_NODES or args.target not in DEFAULT_NODES:
        raise ValueError("unsupported source or target node")
    if args.batch_size <= 0 or args.batch_size > 32:
        raise ValueError("batch size must be between 1 and 32")
    if args.confirm_root != args.partition_root:
        raise ValueError("--confirm-root must exactly match --partition-root")
    os.makedirs(args.evidence_dir, exist_ok=True)
    routes = load_jsonl(args.active_routes)
    zk = DockerZk(args.zk_container, args.zk_server, args.partition_root, args.docker_bin)
    batch_number = 0

    while True:
        snapshots = zk.read_all(args.partitions)
        current_rows = [record["value"] for record in snapshots]
        validate(current_rows, args.partitions, DEFAULT_NODES)
        selected = select_source_partitions(current_rows, args.source, args.batch_size)
        if not selected:
            print(f"drain_complete source={args.source} target={args.target} batches={batch_number}")
            return
        batch_number += 1
        by_id = {row["partitionId"]: row for row in current_rows}

        learner_evidence = parse_ready_evidence(zk.logs(args.target_container, args.learner_since))
        require_route_evidence(
            routes,
            by_id,
            args.target,
            "LEARNER",
            learner_evidence,
            args.partitions,
            selected,
        )

        recovering_rows, _ = plan_primary_drain(
            current_rows, args.partitions, args.source, args.target, DEFAULT_NODES
        )
        selected_set = set(selected)
        recovering_rows = [
            row for row in recovering_rows if row["partitionId"] in selected_set
        ]
        recovering_records = plan_records(
            snapshots,
            recovering_rows,
            "drain-recovering",
            source=args.source,
            target=args.target,
        )
        recovering_path = evidence_path(
            args.evidence_dir, args.source, args.target, batch_number, "recovering"
        )
        recovering_plan = save_plan(
            recovering_path,
            "drain-recovering",
            recovering_records,
            partitionRoot=args.partition_root,
            source=args.source,
            target=args.target,
            targetContainer=args.target_container,
            activeRoutes=args.active_routes,
        )
        apply_records(
            zk,
            recovering_records,
            "drain-recovering",
            args.batch_size,
            source=args.source,
            target=args.target,
        )

        recovering_by_id = {
            record["partitionId"]: record["desired"] for record in recovering_records
        }
        wait_primary_ready(
            zk,
            routes,
            recovering_by_id,
            args.target,
            selected,
            args.target_container,
            recovering_plan["createdAt"],
            args.ready_timeout,
        )

        current_recovering = zk.read_many(selected)
        for record in current_recovering:
            if canonical(record["value"]) != canonical(recovering_by_id[record["partitionId"]]):
                raise RuntimeError(f"recovering assignment changed: {record['partitionId']}")
        ready_records = [
            {**record, "desired": ready_value(record["value"])}
            for record in current_recovering
        ]
        ready_path = evidence_path(
            args.evidence_dir, args.source, args.target, batch_number, "ready"
        )
        save_plan(
            ready_path,
            "promote-ready",
            ready_records,
            partitionRoot=args.partition_root,
            source=args.source,
            target=args.target,
            recoveryPlan=recovering_path,
        )
        apply_records(zk, ready_records, "promote-ready", args.batch_size)
        print(
            f"batch_complete={batch_number} source={args.source} target={args.target} "
            f"partitions={selected[0]}..{selected[-1]}",
            flush=True,
        )


def parser():
    result = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    result.add_argument("--source", required=True)
    result.add_argument("--target", required=True)
    result.add_argument("--active-routes", required=True)
    result.add_argument("--target-container", required=True)
    result.add_argument("--learner-since", required=True)
    result.add_argument("--evidence-dir", required=True)
    result.add_argument("--batch-size", type=int, default=8)
    result.add_argument("--ready-timeout", type=int, default=60)
    result.add_argument("--zk-container", default="dc-saas-zookeeper")
    result.add_argument("--zk-server", default="127.0.0.1:32181")
    result.add_argument("--partition-root", default=DEFAULT_ROOT)
    result.add_argument("--partitions", type=int, default=256)
    result.add_argument("--docker-bin", default="docker")
    result.add_argument("--confirm-root", required=True)
    return result


def main(argv=None):
    run(parser().parse_args(argv))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
