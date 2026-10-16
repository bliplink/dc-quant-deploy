#!/usr/bin/env python3
"""Read-only Trade A/B failback preflight for the 2026-10-16 Demo.

This is *not* a promotion controller. A/B control-plane READY, WAL file sizes,
replication-health watermarks, and matching bootstrap snapshots do not prove a
durable, fenced live-primary handoff. It never changes ZooKeeper or containers.
The odd-partition candidate heuristic is specific to this Demo's original
alternating A/B placement, and MUST NOT be used as promotion authority.
"""
import argparse
from collections import Counter
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from md_cluster_transition_host import DockerZk  # noqa: E402

HEALTH_ROOT = "/dc/cluster/tradesvr/controller/replication-health"
PARTITION_ROOT = "/dc/cluster/tradesvr/partitions"
NODES = ("TradeSvrA", "TradeSvrB")
PARTITION_ID = re.compile(r"^P[0-9]{3}$")
MANDATORY_BLOCKERS = [
    "SOURCE_FENCED_DURABLE_HEAD_AND_RECEIVER_FULL_WAL_ATTESTATION_NOT_VERIFIED",
    "LIVE_PRIMARY_WRITE_DRAIN_AND_EPOCH_FENCE_HANDOFF_NOT_IMPLEMENTED",
    "TARGET_BUSINESS_STATE_AND_PROJECTION_AUTHORITY_NOT_VERIFIED",
]


def parse_health_children(output):
    children = None
    for raw in output.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]") and not line.startswith("[zk:"):
            names = [part.strip() for part in line[1:-1].split(",") if part.strip()]
            if children is not None:
                raise ValueError("ambiguous replication-health child list")
            if any(not PARTITION_ID.fullmatch(item) for item in names):
                raise ValueError("unexpected ZooKeeper replication-health entry")
            if len(set(names)) != len(names):
                raise ValueError("duplicate replication-health child")
            children = names
    if children is None:
        raise ValueError("missing ZooKeeper health child list")
    return children


def parse_health_records(output, expected_ids):
    rows = {}
    for raw in output.splitlines():
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid replication-health JSON") from exc
        pid = value.get("partitionId")
        if pid not in expected_ids or pid in rows:
            raise ValueError("unexpected or repeated replication-health partition")
        rows[pid] = value
    if set(rows) != set(expected_ids):
        raise ValueError("incomplete replication-health response")
    return rows


def read_health(zk):
    children = parse_health_children(zk._zk("ls " + HEALTH_ROOT))
    if not children:
        return {}
    command = "\n".join("get " + HEALTH_ROOT + "/" + p for p in children)
    return parse_health_records(zk._zk(command, timeout=45), set(children))


def assess(assignments, health, now_ms, max_health_age_ms=60000):
    """Evaluate non-authorizing hints; any future control path must use fresh proofs."""
    rows = [row["value"] if "value" in row else row for row in assignments]
    if len(rows) != 256 or len({r.get("partitionId") for r in rows}) != 256:
        raise ValueError("full 256-partition inventory required")
    if {r["partitionId"] for r in rows} != {"P%03d" % i for i in range(256)}:
        raise ValueError("incomplete/invalid partition ids")

    counts = Counter((r.get("primary"), r.get("state")) for r in rows)
    candidate_details = []
    # The 2026-10-16 injected fault promoted the original B-owned odd
    # partitions to A, increasing their epoch from 1 to 2.
    candidates = [r for r in rows if int(r["partitionId"][1:]) % 2 == 1
                  and r.get("primary") == "TradeSvrA" and r.get("epoch", 0) >= 2]
    for r in candidates:
        pid = r["partitionId"]
        blockers = []
        if r.get("state") != "READY":
            blockers.append("CONTROL_PLANE_NOT_READY")
        if r.get("replica") != "TradeSvrB" or r.get("replicas") != ["TradeSvrB"]:
            blockers.append("TARGET_NOT_EXCLUSIVE_ASSIGNED_HOT_REPLICA")
        h = health.get(pid)
        if h is None:
            blockers.append("REPLICATION_HEALTH_MISSING")
        else:
            if h.get("epoch") != r.get("epoch") or h.get("primary") != "TradeSvrA" or h.get("replica") != "TradeSvrB":
                blockers.append("REPLICATION_HEALTH_ROLE_OR_EPOCH_MISMATCH")
            if h.get("degraded") is not False:
                blockers.append("REPLICATION_DEGRADED_OR_UNKNOWN")
            if (not isinstance(h.get("replicatedSeq"), int)
                    or h["replicatedSeq"] <= 0):
                blockers.append("DURABLE_REPLICA_WATERMARK_NOT_POSITIVE")
            updated = h.get("updatedAt")
            if (not isinstance(updated, int) or updated > now_ms
                    or now_ms - updated > max_health_age_ms):
                blockers.append("REPLICATION_HEALTH_STALE")
        candidate_details.append({"partitionId": pid, "epoch": r["epoch"],
                                  "healthWatermark": h.get("replicatedSeq") if h else None,
                                  "preliminaryBlockers": blockers})

    reason_counts = dict(sorted(Counter(reason for item in candidate_details
                                        for reason in item["preliminaryBlockers"]).items()))
    return {
        "mode": "READ_ONLY_NON_AUTHORIZING",
        "partitionCount": len(rows),
        "primaryCounts": dict(Counter(r.get("primary") for r in rows)),
        "stateCounts": dict(Counter(r.get("state") for r in rows)),
        "epochCounts": dict(sorted(Counter(str(r.get("epoch")) for r in rows).items())),
        "healthRecordCount": len(health),
        "inferredFormerBPrimaryCandidates": len(candidates),
        "candidatesWithCleanPreliminaryHealth": sum(not item["preliminaryBlockers"] for item in candidate_details),
        "candidateBlockerCounts": reason_counts,
        "candidateSample": candidate_details[:16],
        "mandatoryBlockers": list(MANDATORY_BLOCKERS),
        "automaticPrimaryChangeAuthorized": False,
        "safeToSigkillAForReverseTest": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zk-container", default="dc-saas-zookeeper")
    parser.add_argument("--zk-server", default="127.0.0.1:32181")
    parser.add_argument("--max-health-age-seconds", type=int, default=60)
    parser.add_argument("--output", help="write one JSON evidence report (no container or ZK changes)")
    args = parser.parse_args(argv)
    if args.max_health_age_seconds <= 0:
        parser.error("max-health-age-seconds must be positive")
    zk = DockerZk(args.zk_container, args.zk_server, PARTITION_ROOT, "docker")
    try:
        rows = zk.read_all(256)
        health = read_health(zk)
        result = assess(rows, health, int(time.time() * 1000),
                        args.max_health_age_seconds * 1000)
    except Exception as exc:
        result = {
            "mode": "READ_ONLY_NON_AUTHORIZING",
            "automaticPrimaryChangeAuthorized": False,
            "safeToSigkillAForReverseTest": False,
            "mandatoryBlockers": ["PRECHECK_EVIDENCE_UNAVAILABLE", *MANDATORY_BLOCKERS],
            "error": str(exc)[:400],
        }
    result["checkedAt"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    body = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(body, encoding="utf-8")
    print(body, end="")
    return 0 if "error" not in result else 2


if __name__ == "__main__":
    sys.exit(main())
