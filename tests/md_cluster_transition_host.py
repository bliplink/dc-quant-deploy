#!/usr/bin/env python3
"""Safely stage and promote MDSvr assignments with ZooKeeper version CAS.

The command is dry-run by default.  Production writes require both ``--apply``
and an exact ``--confirm-root`` value.  Each write re-reads the znode, compares
its payload and dataVersion with the captured plan, performs a versioned set,
and reads the value back before continuing.
"""

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import zlib

try:
    from tests.md_cluster_assignment_plan import (
        plan_primary_drain,
        stage_learner,
        validate,
    )
except ModuleNotFoundError:
    # Host operators invoke this file directly from the deployment checkout.
    from md_cluster_assignment_plan import plan_primary_drain, stage_learner, validate


DEFAULT_ROOT = "/dc/cluster/mdsvr/partitions"
DEFAULT_NODES = {"MDSvrA", "MDSvrB", "MDSvrC"}
DATA_VERSION = re.compile(r"^dataVersion\s*=\s*([0-9]+)\s*$", re.MULTILINE)
READY_LINE = re.compile(
    r"MD_MARKET_READY node:(?P<node>[^,]+), partition:(?P<partition>P[0-9]{3}), "
    r"epoch:(?P<epoch>[0-9]+), role:(?P<role>[^,]+), location:(?P<location>[^,]+), "
    r"market:(?P<market>[^,]+), securityId:(?P<security>[^,\s]+)"
)


def utc_now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical(value):
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def parse_zk_get(output, partition_id):
    payloads = []
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if value.get("partitionId") == partition_id:
            payloads.append(value)
    versions = DATA_VERSION.findall(output)
    if len(payloads) != 1 or len(versions) != 1:
        raise RuntimeError(
            f"could not parse one payload/dataVersion for {partition_id}: "
            f"payloads={len(payloads)} versions={len(versions)}"
        )
    return payloads[0], int(versions[0])


def parse_zk_get_many(output, expected_ids):
    expected_ids = set(expected_ids)
    result = {}
    pending = None
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            partition_id = value.get("partitionId")
            pending = (partition_id, value) if partition_id in expected_ids else None
            continue
        version = DATA_VERSION.fullmatch(line)
        if version and pending:
            partition_id, value = pending
            if partition_id in result:
                raise RuntimeError(f"duplicate ZooKeeper result: {partition_id}")
            result[partition_id] = (value, int(version.group(1)))
            pending = None
    missing = expected_ids - set(result)
    if missing:
        raise RuntimeError(f"missing ZooKeeper results: {','.join(sorted(missing)[:10])}")
    return result


def partition_for_route(route, partition_count):
    values = [route.get("location"), route.get("marketIndicator"), route.get("securityID")]
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"invalid active route: {route}")
    key = "\x1f".join(value.strip() for value in values)
    return f"P{zlib.crc32(key.encode('utf-8')) % partition_count:03d}"


def parse_ready_evidence(log_text):
    evidence = set()
    for match in READY_LINE.finditer(log_text):
        evidence.add(
            (
                match.group("node"),
                match.group("partition"),
                int(match.group("epoch")),
                match.group("role"),
                match.group("location"),
                match.group("market"),
                match.group("security"),
            )
        )
    return evidence


def require_route_evidence(routes, assignments, node, role, evidence, partition_count, selected=None):
    required = []
    selected = set(selected or assignments)
    for route in routes:
        partition_id = partition_for_route(route, partition_count)
        if partition_id not in selected:
            continue
        assignment = assignments[partition_id]
        item = (
            node,
            partition_id,
            int(assignment["epoch"]),
            role,
            route["location"].strip(),
            route["marketIndicator"].strip(),
            route["securityID"].strip(),
        )
        if item not in evidence:
            required.append(item)
    if required:
        sample = "; ".join(str(item) for item in required[:5])
        raise RuntimeError(f"missing MD_MARKET_READY evidence ({len(required)} routes): {sample}")


def validate_transition(current, desired, operation, learner=None, source=None, target=None):
    if current.get("partitionId") != desired.get("partitionId"):
        raise ValueError("partitionId changed")
    current_version = int(current.get("assignmentVersion", 0))
    desired_version = int(desired.get("assignmentVersion", 0))
    if desired_version != current_version + 1:
        raise ValueError("assignmentVersion must increase exactly once")

    if operation == "stage-learner":
        if current.get("state") != "READY" or desired.get("state") != "READY":
            raise ValueError("learner staging requires READY assignments")
        for field in ("epoch", "primary", "replica", "replicas"):
            if current.get(field) != desired.get(field):
                raise ValueError(f"learner staging changed {field}")
        before = set(current.get("learners") or [])
        after = set(desired.get("learners") or [])
        if after != before | {learner}:
            raise ValueError("learner staging changed an unexpected learner")
        return

    if operation == "drain-recovering":
        if current.get("state") != "READY" or desired.get("state") != "RECOVERING":
            raise ValueError("drain must move READY to RECOVERING")
        if current.get("primary") != source or desired.get("primary") != target:
            raise ValueError("drain primary transition does not match source/target")
        if int(desired.get("epoch", 0)) != int(current.get("epoch", 0)) + 1:
            raise ValueError("drain epoch must increase exactly once")
        hot_nodes = set(current.get("replicas") or [current.get("replica")]) | set(
            current.get("learners") or []
        )
        if target not in hot_nodes:
            raise ValueError("drain target did not own hot state")
        return

    if operation == "promote-ready":
        if current.get("state") != "RECOVERING" or desired.get("state") != "READY":
            raise ValueError("promotion must move RECOVERING to READY")
        for field in ("epoch", "primary", "replica", "replicas", "learners"):
            if current.get(field) != desired.get(field):
                raise ValueError(f"promotion changed {field}")
        return

    raise ValueError(f"unsupported operation: {operation}")


class DockerZk:
    def __init__(self, container, server, root, docker="docker"):
        self.container = container
        self.server = server
        self.root = root.rstrip("/")
        self.docker = docker

    def _zk(self, command, timeout=30):
        result = subprocess.run(
            [self.docker, "exec", "-i", self.container, "zkCli.sh", "-server", self.server],
            input=command + "\nquit\n",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0 or "KeeperErrorCode" in result.stdout or "Exception" in result.stdout:
            raise RuntimeError(f"ZooKeeper command failed: {result.stdout[-1200:]}")
        return result.stdout

    def read(self, partition_id):
        path = f"{self.root}/{partition_id}"
        value, version = parse_zk_get(self._zk(f"get -s {path}"), partition_id)
        return {"partitionId": partition_id, "path": path, "version": version, "value": value}

    def read_all(self, count):
        partition_ids = [f"P{index:03d}" for index in range(count)]
        commands = "\n".join(f"get -s {self.root}/{partition_id}" for partition_id in partition_ids)
        values = parse_zk_get_many(self._zk(commands, timeout=90), partition_ids)
        return [
            {
                "partitionId": partition_id,
                "path": f"{self.root}/{partition_id}",
                "version": values[partition_id][1],
                "value": values[partition_id][0],
            }
            for partition_id in partition_ids
        ]

    def cas(self, record, desired):
        current = self.read(record["partitionId"])
        if current["version"] != record["version"] or canonical(current["value"]) != canonical(record["value"]):
            raise RuntimeError(f"CAS precondition changed: {record['partitionId']}")
        self._zk(f"set -v {record['version']} {record['path']} {canonical(desired)}")
        written = self.read(record["partitionId"])
        if written["version"] != record["version"] + 1 or canonical(written["value"]) != canonical(desired):
            raise RuntimeError(f"CAS verification failed: {record['partitionId']}")
        return written

    def logs(self, container, since):
        result = subprocess.run(
            [self.docker, "logs", "--since", since, container],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"could not read {container} logs: {result.stdout[-1200:]}")
        return result.stdout


def load_jsonl(path):
    with open(path, encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def save_plan(path, operation, records, **metadata):
    plan = {"schemaVersion": 1, "operation": operation, "createdAt": utc_now(), "records": records}
    plan.update(metadata)
    with open(path, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    return plan


def load_plan(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def require_apply_confirmation(args):
    if args.apply and args.confirm_root != args.partition_root:
        raise ValueError("--apply requires --confirm-root to exactly match --partition-root")


def plan_records(snapshots, desired_rows, operation, **context):
    by_id = {row["partitionId"]: row for row in desired_rows}
    records = []
    for snapshot in snapshots:
        desired = by_id.get(snapshot["partitionId"])
        if desired is None or canonical(desired) == canonical(snapshot["value"]):
            continue
        validate_transition(snapshot["value"], desired, operation, **context)
        records.append({**snapshot, "desired": desired})
    return records


def apply_records(zk, records, operation, **context):
    for index, record in enumerate(records, 1):
        validate_transition(record["value"], record["desired"], operation, **context)
        zk.cas(record, record["desired"])
        print(f"applied={index}/{len(records)} partition={record['partitionId']}", flush=True)


def command_stage(args, zk):
    snapshots = zk.read_all(args.partitions)
    current = [record["value"] for record in snapshots]
    desired = stage_learner(current, args.partitions, args.learner, DEFAULT_NODES)
    records = plan_records(snapshots, desired, "stage-learner", learner=args.learner)
    save_plan(args.plan, "stage-learner", records, partitionRoot=args.partition_root, learner=args.learner)
    print(f"plan={args.plan} changes={len(records)} apply={str(args.apply).lower()}")
    if args.apply:
        apply_records(zk, records, "stage-learner", learner=args.learner)


def command_drain(args, zk):
    snapshots = zk.read_all(args.partitions)
    current = [record["value"] for record in snapshots]
    by_id = validate(current, args.partitions, DEFAULT_NODES)
    selected = [
        partition_id for partition_id in sorted(by_id)
        if by_id[partition_id].get("primary") == args.from_node
    ]
    if args.partition:
        requested = set(args.partition)
        selected = [partition_id for partition_id in selected if partition_id in requested]
        if set(selected) != requested:
            raise ValueError("a requested partition is not currently primary on the source node")
    selected = selected[: args.limit]
    if not selected:
        raise ValueError("no source-primary partitions selected")

    if args.active_routes:
        routes = load_jsonl(args.active_routes)
        evidence = parse_ready_evidence(zk.logs(args.target_container, args.since))
        require_route_evidence(
            routes, by_id, args.to_node, "LEARNER", evidence, args.partitions, selected
        )

    recovering, _ = plan_primary_drain(
        current, args.partitions, args.from_node, args.to_node, DEFAULT_NODES
    )
    desired = [row for row in recovering if row["partitionId"] in set(selected)]
    records = plan_records(
        snapshots, desired, "drain-recovering", source=args.from_node, target=args.to_node
    )
    save_plan(
        args.plan,
        "drain-recovering",
        records,
        partitionRoot=args.partition_root,
        source=args.from_node,
        target=args.to_node,
        targetContainer=args.target_container,
        activeRoutes=args.active_routes,
    )
    print(f"plan={args.plan} changes={len(records)} apply={str(args.apply).lower()}")
    if args.apply:
        apply_records(
            zk, records, "drain-recovering", source=args.from_node, target=args.to_node
        )


def command_promote(args, zk):
    recovery = load_plan(args.recovery_plan)
    if recovery.get("operation") != "drain-recovering":
        raise ValueError("recovery plan has the wrong operation")
    routes = load_jsonl(args.active_routes) if args.active_routes else []
    logs = zk.logs(args.target_container, recovery["createdAt"])
    evidence = parse_ready_evidence(logs)
    records = []
    current_by_id = {}
    for recovery_record in recovery["records"]:
        current = zk.read(recovery_record["partitionId"])
        if canonical(current["value"]) != canonical(recovery_record["desired"]):
            raise RuntimeError(f"recovering assignment changed: {current['partitionId']}")
        desired = json.loads(canonical(current["value"]))
        desired["state"] = "READY"
        desired["assignmentVersion"] = int(desired.get("assignmentVersion", 0)) + 1
        validate_transition(current["value"], desired, "promote-ready")
        records.append({**current, "desired": desired})
        current_by_id[current["partitionId"]] = current["value"]

    require_route_evidence(
        routes,
        current_by_id,
        recovery["target"],
        "PRIMARY",
        evidence,
        args.partitions,
        current_by_id,
    )
    save_plan(
        args.plan,
        "promote-ready",
        records,
        partitionRoot=args.partition_root,
        recoveryPlan=args.recovery_plan,
        target=recovery["target"],
    )
    print(f"plan={args.plan} changes={len(records)} apply={str(args.apply).lower()}")
    if args.apply:
        apply_records(zk, records, "promote-ready")


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--zk-container", default="dc-saas-zookeeper")
    result.add_argument("--zk-server", default="127.0.0.1:32181")
    result.add_argument("--partition-root", default=DEFAULT_ROOT)
    result.add_argument("--partitions", type=int, default=256)
    result.add_argument("--docker-bin", default="docker")
    sub = result.add_subparsers(dest="command", required=True)

    stage = sub.add_parser("stage-learner")
    stage.add_argument("--learner", default="MDSvrC")
    stage.add_argument("--plan", required=True)

    drain = sub.add_parser("drain-recovering")
    drain.add_argument("--from-node", required=True)
    drain.add_argument("--to-node", required=True)
    drain.add_argument("--partition", action="append")
    drain.add_argument("--limit", type=int, default=8)
    drain.add_argument("--active-routes")
    drain.add_argument("--target-container", default="dc-saas-mdsvr-c")
    drain.add_argument("--since", required=True)
    drain.add_argument("--plan", required=True)

    promote = sub.add_parser("promote-ready")
    promote.add_argument("--recovery-plan", required=True)
    promote.add_argument("--active-routes")
    promote.add_argument("--target-container", default="dc-saas-mdsvr-c")
    promote.add_argument("--plan", required=True)

    for command in (stage, drain, promote):
        command.add_argument("--apply", action="store_true")
        command.add_argument("--confirm-root")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    require_apply_confirmation(args)
    zk = DockerZk(args.zk_container, args.zk_server, args.partition_root, args.docker_bin)
    if args.command == "stage-learner":
        command_stage(args, zk)
    elif args.command == "drain-recovering":
        command_drain(args, zk)
    else:
        command_promote(args, zk)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
