#!/usr/bin/env python3
"""Read and CAS-update one isolated Order assignment from zkCli get -s output."""

import json
import re
import sys


def parse_get_output(output, partition_id):
    assignments = []
    versions = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("{"):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and value.get("partitionId") == partition_id:
                assignments.append(value)
        match = re.fullmatch(r"dataVersion = (\d+)", line)
        if match:
            versions.append(int(match.group(1)))
    if len(assignments) != 1 or len(versions) != 1:
        raise ValueError("expected exactly one assignment and dataVersion")
    return assignments[0], versions[0]


def transition(assignment, version, path, epoch, primary, replica, expected_epoch, expected_primary):
    partition_id = path.rsplit("/", 1)[-1]
    if assignment.get("partitionId") != partition_id or assignment.get("state") != "READY":
        raise ValueError("partition assignment is not READY")
    if int(assignment.get("epoch", 0)) != expected_epoch or assignment.get("primary") != expected_primary:
        raise ValueError("partition assignment changed before transition")
    if not isinstance(epoch, int) or epoch <= int(assignment.get("epoch", 0)):
        raise ValueError("transition epoch must advance")
    if primary not in {"OrderSvrA", "OrderSvrB"} or replica not in {"OrderSvrA", "OrderSvrB"} \
            or primary == replica:
        raise ValueError("unsupported isolated A/B topology")
    if assignment.get("learners"):
        raise ValueError("isolated fault test does not support learners")
    if "replicas" in assignment and len(assignment["replicas"]) != 1:
        raise ValueError("isolated fault test requires one replica")
    updated = dict(assignment)
    updated.update({"epoch": epoch, "primary": primary, "replica": replica, "state": "READY"})
    if "replicas" in updated:
        updated["replicas"] = [replica]
    if "assignmentVersion" in updated:
        updated["assignmentVersion"] = int(updated["assignmentVersion"]) + 1
    payload = json.dumps(updated, separators=(",", ":"))
    return "set -v %d %s %s" % (version, path, payload)


def main(argv):
    if len(argv) < 3 or argv[1] not in {"read", "transition"}:
        raise ValueError("usage: order_cluster_zk_assignment.py read|transition PATH [EPOCH PRIMARY REPLICA]")
    path = argv[2]
    if not re.fullmatch(r"/dc/cluster/ordersvr-dev/partitions/P\d{3}", path):
        raise ValueError("only isolated Order cluster partition paths are allowed")
    assignment, version = parse_get_output(sys.stdin.read(), path.rsplit("/", 1)[-1])
    if argv[1] == "read" and len(argv) == 3:
        print(json.dumps(assignment, separators=(",", ":")))
    elif argv[1] == "transition" and len(argv) == 8:
        print(transition(assignment, version, path, int(argv[3]), argv[4], argv[5],
                         int(argv[6]), argv[7]))
    else:
        raise ValueError("invalid arguments")


if __name__ == "__main__":
    try:
        main(sys.argv)
    except (ValueError, TypeError, KeyError) as exc:
        print("assignment parser error: %s" % exc, file=sys.stderr)
        sys.exit(1)
