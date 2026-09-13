#!/usr/bin/env python3
"""Validate OrderSvr assignments and their persisted snapshot boundary."""

import collections
import json
import os
import sys


ALLOWED_NODES = {"OrderSvrA", "OrderSvrB", "OrderSvrC"}


def verify(assignment_path, expected, data_root, verify_learners=False):
    with open(assignment_path, encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]

    by_id = {row.get("partitionId"): row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError("assignment input contains duplicate partitionId rows")

    expected_ids = {f"P{index:03d}" for index in range(expected)}
    if set(by_id) != expected_ids:
        missing = sorted(expected_ids - set(by_id))
        extra = sorted(set(by_id) - expected_ids)
        raise ValueError(
            f"assignment set mismatch missing={missing[:8]} extra={extra[:8]}"
        )

    states = collections.Counter(row.get("state") for row in rows)
    epochs = collections.Counter(row.get("epoch") for row in rows)
    primaries = collections.Counter(row.get("primary") for row in rows)
    replicas = collections.Counter(
        node
        for row in rows
        for node in (row.get("replicas") or [row.get("replica")])
    )
    learners = collections.Counter(
        node for row in rows for node in (row.get("learners") or [])
    )

    if states != {"READY": expected}:
        raise ValueError(f"not all assignments are READY: {dict(states)}")

    for partition_id, row in by_id.items():
        epoch = row.get("epoch")
        if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch <= 0:
            raise ValueError(f"invalid epoch {partition_id}: {epoch}")
        primary = row.get("primary")
        replica_nodes = row.get("replicas") or [row.get("replica")]
        learner_nodes = row.get("learners") or []
        nodes = [primary] + replica_nodes + learner_nodes
        if (
            primary not in ALLOWED_NODES
            or not replica_nodes
            or any(node not in ALLOWED_NODES for node in nodes)
        ):
            raise ValueError(f"invalid topology {partition_id}: {row}")
        if primary in replica_nodes or len(set(replica_nodes)) != len(replica_nodes):
            raise ValueError(f"invalid replicas {partition_id}: {row}")
        if primary in learner_nodes or set(replica_nodes).intersection(learner_nodes):
            raise ValueError(f"invalid learners {partition_id}: {row}")

    uppercase_sn = 0
    for partition_id, assignment in sorted(by_id.items()):
        values = []
        replica_nodes = assignment.get("replicas") or [assignment.get("replica")]
        nodes = [assignment.get("primary")] + replica_nodes
        if verify_learners:
            nodes += assignment.get("learners") or []
        nodes = list(dict.fromkeys(nodes))
        for node in nodes:
            path = os.path.join(
                data_root, node, "snapshot", partition_id, "snapshot.json"
            )
            if not os.path.isfile(path):
                raise ValueError(f"missing snapshot: {path}")
            with open(path, encoding="utf-8") as stream:
                value = json.load(stream)
            if value.get("partitionId") != partition_id:
                raise ValueError(f"snapshot partition mismatch: {path}")
            if value.get("epoch") != assignment.get("epoch"):
                raise ValueError(
                    f"snapshot epoch mismatch {partition_id} node={node} "
                    f"snapshot={value.get('epoch')} "
                    f"assignment={assignment.get('epoch')}"
                )
            uppercase_sn += sum(
                1
                for book in value.get("books", [])
                for order in book.get("orders", [])
                if "SN" in order
            )
            values.append(value)
        if any(value != values[0] for value in values[1:]):
            raise ValueError(
                f"assigned snapshot mismatch: {partition_id} nodes={nodes}"
            )

    if uppercase_sn:
        raise ValueError(
            f"snapshots contain {uppercase_sn} side-effectful uppercase SN fields"
        )

    epoch_counts = dict(sorted(epochs.items()))
    return {
        "partitions": expected,
        "ready": states["READY"],
        "epochMin": min(epochs),
        "epochMax": max(epochs),
        "epochCounts": epoch_counts,
        "mixedEpochs": len(epochs) > 1,
        "primaries": dict(sorted(primaries.items())),
        "replicas": dict(sorted(replicas.items())),
        "learners": dict(sorted(learners.items())),
        "snapshotSetsEqual": expected,
        "verifyLearners": verify_learners,
    }


def main(argv):
    if len(argv) != 5:
        raise SystemExit(
            "usage: verify_order_cluster_assignments.py "
            "<assignments.jsonl> <partition-count> <data-root> <verify-learners>"
        )
    result = verify(
        argv[1], int(argv[2]), argv[3], argv[4].strip().lower() == "true"
    )
    print(
        "partitions={partitions} ready={ready} epoch_min={epochMin} "
        "epoch_max={epochMax} mixed_epochs={mixedEpochs} epoch_counts={epochCounts}".format(
            **result
        )
    )
    print(f"primaries={result['primaries']}")
    print(f"replicas={result['replicas']}")
    print(f"learners={result['learners']}")
    print(
        f"snapshot_sets_equal={result['snapshotSetsEqual']} "
        f"verify_learners={result['verifyLearners']} uppercase_SN=0"
    )


if __name__ == "__main__":
    try:
        main(sys.argv)
    except ValueError as error:
        raise SystemExit(str(error))
