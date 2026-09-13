#!/usr/bin/env python3
"""Build validated legacy MDSvr learner and primary-drain assignment plans."""

import copy
import json
import re


PARTITION_ID = re.compile(r"^P[0-9]{3}$")


def replica_nodes(row):
    values = row.get("replicas")
    if values is None:
        values = [row.get("replica")]
    return [value for value in values if value]


def learner_nodes(row):
    return [value for value in (row.get("learners") or []) if value]


def validate(rows, expected, allowed_nodes):
    by_id = {}
    for row in rows:
        partition_id = row.get("partitionId")
        if not isinstance(partition_id, str) or not PARTITION_ID.fullmatch(partition_id):
            raise ValueError(f"invalid partitionId: {partition_id}")
        if partition_id in by_id:
            raise ValueError(f"duplicate partitionId: {partition_id}")
        by_id[partition_id] = row

    expected_ids = {f"P{index:03d}" for index in range(expected)}
    if set(by_id) != expected_ids:
        raise ValueError("assignment set does not match the expected legacy partitions")

    for partition_id, row in by_id.items():
        if row.get("state") != "READY":
            raise ValueError(f"partition is not READY: {partition_id}")
        epoch = row.get("epoch")
        if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch <= 0:
            raise ValueError(f"invalid epoch {partition_id}: {epoch}")
        primary = row.get("primary")
        replicas = replica_nodes(row)
        learners = learner_nodes(row)
        if primary not in allowed_nodes or any(
            node not in allowed_nodes for node in replicas + learners
        ):
            raise ValueError(f"unsupported node in {partition_id}")
        if not replicas:
            raise ValueError(f"partition has no replica: {partition_id}")
        if primary in replicas or primary in learners:
            raise ValueError(f"primary appears in another role: {partition_id}")
        if len(replicas) != len(set(replicas)):
            raise ValueError(f"duplicate replica: {partition_id}")
        if len(learners) != len(set(learners)):
            raise ValueError(f"duplicate learner: {partition_id}")
        if set(replicas).intersection(learners):
            raise ValueError(f"replica/learner overlap: {partition_id}")
    return by_id


def _bump_assignment_version(row, increments=1):
    value = row.get("assignmentVersion", 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"invalid assignmentVersion: {value}")
    row["assignmentVersion"] = value + increments


def stage_learner(rows, expected, learner, allowed_nodes):
    by_id = validate(rows, expected, allowed_nodes)
    planned = []
    for partition_id in sorted(by_id):
        original = by_id[partition_id]
        value = copy.deepcopy(original)
        if learner == value.get("primary") or learner in replica_nodes(value):
            raise ValueError(f"learner already has a serving role: {partition_id}")
        learners = learner_nodes(value)
        if learner not in learners:
            learners.append(learner)
            value["learners"] = learners
            _bump_assignment_version(value)
        planned.append(value)
    validate(planned, expected, allowed_nodes)
    return planned


def plan_primary_drain(rows, expected, drain_node, target_node, allowed_nodes):
    by_id = validate(rows, expected, allowed_nodes)
    recovering = []
    ready = []
    for partition_id in sorted(by_id):
        original = by_id[partition_id]
        if original.get("primary") != drain_node:
            continue
        replicas = replica_nodes(original)
        learners = learner_nodes(original)
        if target_node not in replicas and target_node not in learners:
            raise ValueError(
                f"drain target does not own hot state: {partition_id} target={target_node}"
            )

        value = copy.deepcopy(original)
        value["epoch"] = original["epoch"] + 1
        value["primary"] = target_node
        new_replicas = [node for node in replicas if node != target_node]
        if drain_node not in new_replicas:
            new_replicas.append(drain_node)
        value["replicas"] = new_replicas
        value["replica"] = new_replicas[0]
        value["learners"] = [
            node for node in learners if node not in (target_node, drain_node)
        ]
        value["state"] = "RECOVERING"
        _bump_assignment_version(value)
        recovering.append(value)

        ready_value = copy.deepcopy(value)
        ready_value["state"] = "READY"
        _bump_assignment_version(ready_value)
        ready.append(ready_value)

    if not recovering:
        raise ValueError(f"node has no primary partitions to drain: {drain_node}")
    return recovering, ready


def read_jsonl(path):
    with open(path, encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, separators=(",", ":"), sort_keys=True))
            stream.write("\n")
