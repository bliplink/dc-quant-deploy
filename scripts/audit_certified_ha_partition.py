#!/usr/bin/env python3
"""Read-only physical/ZK audit for one Common-backed HA partition.

Does not write ZooKeeper, WAL, container state, or business databases.
Run on the Docker host. A missing fact fails closed rather than reporting PASS.
"""
import argparse
import json
import re
import shlex
import subprocess
import sys


def execute(argv, input_text=None, timeout=40):
    proc = subprocess.run(
        argv, input=input_text, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, timeout=timeout, check=False)
    if proc.returncode:
        raise RuntimeError(
            "command failed (exit {}): {}".format(proc.returncode, " ".join(argv[:4])))
    return proc.stdout


def quoted(text):
    return shlex.quote(text)


def zk_assignment(container, root, partition):
    path = root.rstrip("/") + "/" + partition
    output = execute(
        ["docker", "exec", "-i", container, "zkCli.sh", "-server",
         "127.0.0.1:2181"],
        "get {}\nquit\n".format(path), timeout=45)
    candidates = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith('{"partitionId":'):
            candidates.append(json.loads(line))
    if len(candidates) != 1:
        raise RuntimeError("ZK assignment missing or ambiguous for " + path)
    item = candidates[0]
    if item.get("partitionId") != partition or not isinstance(item.get("epoch"), int):
        raise RuntimeError("ZK partition identity or Epoch invalid")
    return item


def physical_metadata(container, root, service, node, partition, epoch):
    folder = "{}/{}/{}/{}/{}/{}/epoch-{}".format(
        root.rstrip("/"), service, node, service, node, partition, epoch)
    wal = folder + "/business.wal"
    index = folder + "/commit-index"
    shell = (
        'test -f {wal} || exit 41; '
        'printf "WAL_BYTES="; wc -c < {wal}; '
        'if test -d {index}; then '
        'find {index} -maxdepth 1 -type f -name "commit-*.bin" | '
        'LC_ALL=C sort | tail -1; '
        'fi').format(wal=quoted(wal), index=quoted(index))
    output = execute(["docker", "exec", container, "sh", "-c", shell], timeout=65)
    match = re.search(r"WAL_BYTES=\s*(\d+)", output)
    if not match:
        raise RuntimeError("physical WAL size missing for " + node)
    commits = re.findall(r"commit-(\d+)\.bin", output)
    return {"node": node, "wal": wal, "bytes": int(match.group(1)),
            "committed_head": int(commits[-1]) if commits else None}


def physical_prefix_equal(container, a, b):
    smaller = min(a["bytes"], b["bytes"])
    script = "cmp -n {} {} {}".format(
        smaller, quoted(a["wal"]), quoted(b["wal"]))
    try:
        execute(["docker", "exec", container, "sh", "-c", script], timeout=65)
        return True
    except RuntimeError:
        return False


def failure_evidence(container, partition):
    # Match this partition specifically, not generic errors from other shards.
    logs = execute(["docker", "logs", "--tail", "15000", container], timeout=45)
    poisoned = ("Common poisoned primary Epoch cannot renew" in logs)
    writer_missing = ("Common physically certified partition writer unavailable: "
                      + partition) in logs
    physical_phase = ("COMMON_COMMIT_PHASE partition=" + partition) in logs
    return {"primary_epoch_poisoned": poisoned,
            "certified_writer_unavailable": writer_missing,
            "uncertain_physical_commit": physical_phase}


def active_watch_threads(container):
    dump = execute(["docker", "exec", container, "jstack", "1"], timeout=40)
    return len(re.findall(r'^"common-failover-cold-\d+"', dump, re.MULTILINE))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--zk-container", required=True)
    p.add_argument("--primary-container", required=True)
    p.add_argument("--replica-container", required=True)
    p.add_argument("--root", required=True, help="Common node WAL root")
    p.add_argument("--zk-root", required=True, help="Partition assignment ZK root")
    p.add_argument("--service", required=True)
    p.add_argument("--partition", required=True)
    args = p.parse_args()
    if not re.fullmatch(r"P\d{3}", args.partition):
        p.error("--partition must be Pnnn")
    result = {"service": args.service, "partition": args.partition,
              "read_only": True, "verdict": "NO_GO"}
    try:
        assignment = zk_assignment(args.zk_container, args.zk_root, args.partition)
        result["assignment"] = {
            k: assignment.get(k) for k in
            ["epoch", "state", "primary", "replica", "assignmentVersion"]}
        if not assignment.get("primary") or not assignment.get("replica"):
            raise RuntimeError("ZK primary or replica absent")
        epoch = assignment["epoch"]
        a = physical_metadata(args.primary_container, args.root, args.service,
                              assignment["primary"], args.partition, epoch)
        b = physical_metadata(args.primary_container, args.root, args.service,
                              assignment["replica"], args.partition, epoch)
        result["wal"] = {"primary_bytes": a["bytes"], "replica_bytes": b["bytes"],
                         "extra_primary_bytes": a["bytes"] - b["bytes"],
                         "certified_primary_head": a["committed_head"],
                         "replica_commit_index_head": b["committed_head"],
                         "same_common_prefix": physical_prefix_equal(
                             args.primary_container, a, b)}
        result["primary_failure"] = failure_evidence(
            args.primary_container, args.partition)
        result["replica_automatic_watch_threads"] = active_watch_threads(
            args.replica_container)
        issues = []
        if not result["wal"]["same_common_prefix"]:
            issues.append("REPLICA_WAL_PREFIX_DIVERGES")
        if result["wal"]["certified_primary_head"] is None:
            issues.append("CERTIFIED_COMMIT_INDEX_MISSING")
        if (assignment.get("state") == "READY" and
                (result["primary_failure"]["certified_writer_unavailable"] or
                 result["primary_failure"]["primary_epoch_poisoned"])):
            issues.append("ZK_READY_BUT_PRIMARY_PHYSICAL_WRITER_UNAVAILABLE")
        if result["replica_automatic_watch_threads"] == 0:
            issues.append("REPLICA_AUTOMATIC_FAILOVER_WATCH_NOT_RUNNING")
        result["issues"] = issues
        result["verdict"] = "PASS" if not issues else "NO_GO"
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        result["issues"] = ["INCOMPLETE_OR_UNVERIFIABLE_EVIDENCE"]
        result["diagnostic"] = str(exc)[:300]
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if result["verdict"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
