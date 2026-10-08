#!/usr/bin/env python3
"""Read-only Order HA rollout preflight.

A PASS is *not* permission to restart a node: synchronization, journal, epoch,
service health and transaction consistency still require an operator review.
No command in this program mutates ZooKeeper, Docker, journals or MySQL.
"""
import argparse
import json
import re
import subprocess
import sys

ORDER_NODES = ("OrderSvrA", "OrderSvrB", "OrderSvrC")
CONTAINERS = {
    "OrderSvrA": "dc-saas-ordersvr",
    "OrderSvrB": "dc-saas-ordersvr-b",
    "OrderSvrC": "dc-saas-ordersvr-c",
}
EXPECTED_PARTITIONS = 256
EXPECTED_ROBOTS = 50
EXPECTED_ORDERS = 2000
MIN_AVAILABLE_KIB = 2 * 1024 * 1024
MIN_SWAP_FREE_KIB = 256 * 1024
MAX_CPU_PSI_AVG60 = 30.0


def issues_for_snapshot(snapshot, target, require_topology=True):
    """Evaluate declarative evidence without side effects; fail closed."""
    problems = []
    try:
        resources = snapshot["resources"]
        cpu_psi = float(resources["cpu_some_avg60"])
        mem = int(resources["mem_available_kib"])
        swap = int(resources["swap_free_kib"])
    except (KeyError, ValueError, TypeError) as exc:
        return ["resource evidence unavailable or malformed: " + str(exc)]
    if cpu_psi > MAX_CPU_PSI_AVG60:
        problems.append("VM CPU pressure avg60 %.2f%% exceeds %.0f%%" %
                        (cpu_psi, MAX_CPU_PSI_AVG60))
    if mem < MIN_AVAILABLE_KIB:
        problems.append("VM MemAvailable %d KiB below %d KiB" %
                        (mem, MIN_AVAILABLE_KIB))
    if swap < MIN_SWAP_FREE_KIB:
        problems.append("VM SwapFree %d KiB below %d KiB" %
                        (swap, MIN_SWAP_FREE_KIB))
    nodes = snapshot.get("nodes")
    if not isinstance(nodes, dict) or set(nodes) != set(ORDER_NODES):
        problems.append("incomplete Order A/B/C container evidence")
    else:
        for name in ORDER_NODES:
            item = nodes[name]
            if not isinstance(item, dict) or not item.get("running", False):
                problems.append("%s is not running" % name)
            elif item.get("oom", False) or int(item.get("restarts", -1)) < 0:
                problems.append("%s has unsafe/unknown container state" % name)
    robots = snapshot.get("robots")
    if not isinstance(robots, dict):
        problems.append("Robot evidence unavailable")
    else:
        if robots.get("running") != EXPECTED_ROBOTS or robots.get("other") != 0:
            problems.append("Robot not stable at 50/50 RUNNING")
        if robots.get("open_order_count") != EXPECTED_ORDERS:
            problems.append("Robot open order count is not 2000")
    if not require_topology:
        return problems
    items = snapshot.get("partitions")
    if not isinstance(items, list) or len(items) != EXPECTED_PARTITIONS:
        problems.append("ZooKeeper Order topology is not 256 complete partitions")
        return problems
    seen = set()
    assigned_primary = 0
    assigned_replica = 0
    for p in items:
        if not isinstance(p, dict):
            problems.append("invalid partition entry")
            continue
        pid = p.get("partitionId")
        if not isinstance(pid, str) or pid in seen:
            problems.append("missing or duplicate partition identity")
        seen.add(pid)
        primary = p.get("primary")
        replicas = p.get("replicas", [])
        if not isinstance(replicas, list) or not replicas:
            problems.append("%s missing synchronous replica assignment" % pid)
            continue
        if p.get("state") != "READY" or primary not in ORDER_NODES:
            problems.append("%s is not READY with a known primary" % pid)
        if len(set([primary] + replicas)) != 1 + len(replicas):
            problems.append("%s has overlapping primary/replica owners" % pid)
        if any(node not in ORDER_NODES for node in replicas):
            problems.append("%s refers to unknown replica node" % pid)
        if primary == target:
            assigned_primary += 1
        if target in replicas:
            assigned_replica += 1
    if assigned_primary:
        problems.append("%s still owns %d primary partitions; drain/transfer first" %
                        (target, assigned_primary))
    if assigned_replica:
        problems.append("%s still holds %d synchronous replica assignments; verify/reconfigure durability quorum before stopping" %
                        (target, assigned_replica))
    if len(seen) != EXPECTED_PARTITIONS:
        problems.append("duplicate/missing ZooKeeper partition IDs")
    return problems


def command(argv, *, stdin=None, timeout=20):
    result = subprocess.run(argv, input=stdin, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError("diagnostic command failed (%s): %s" %
                           (argv[0], result.stderr[:250]))
    return result.stdout


def live_snapshot():
    """Fast resource/health checks first; never start costly ZK scan if unsafe."""
    raw = command(["docker", "exec", "dc-saas-zookeeper", "sh", "-lc",
                   "cat /proc/pressure/cpu; grep -E '^(MemAvailable|SwapFree):' /proc/meminfo"])
    m_psi = re.search(r"(?m)^some avg10=[\d.]+ avg60=([\d.]+)", raw)
    m_mem = re.search(r"(?m)^MemAvailable:\s*(\d+) kB", raw)
    m_swap = re.search(r"(?m)^SwapFree:\s*(\d+) kB", raw)
    if not (m_psi and m_mem and m_swap):
        raise RuntimeError("cannot parse VM CPU pressure and memory evidence")
    snapshot = {"resources": {
        "cpu_some_avg60": float(m_psi.group(1)),
        "mem_available_kib": int(m_mem.group(1)),
        "swap_free_kib": int(m_swap.group(1))
    }}
    snapshot["nodes"] = {}
    for name, container in CONTAINERS.items():
        state = command(["docker", "inspect", "-f",
                         "{{.State.Running}} {{.RestartCount}} {{.State.OOMKilled}}", container]).strip().split()
        if len(state) != 3:
            raise RuntimeError("incomplete Docker inspect evidence for " + name)
        snapshot["nodes"][name] = {
            "running": state[0] == "true", "restarts": int(state[1]), "oom": state[2] == "true"
        }
    sql = ("SELECT runtime_status,COUNT(*),COALESCE(SUM(open_order_count),0) "
           "FROM dc_tenant_robot WHERE enabled=1 GROUP BY runtime_status;")
    rows = command(["docker", "exec", "dc-saas-mysql", "sh", "-lc",
                    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N dc -e ' +
                    json.dumps(sql)])
    running = other = count = 0
    for row in rows.splitlines():
        status, quantity, open_orders = row.split("\t")
        if status == "RUNNING":
            running += int(quantity)
        else:
            other += int(quantity)
        count += int(open_orders)
    snapshot["robots"] = {
        "running": running, "other": other, "open_order_count": count
    }
    return snapshot


def load_topology():
    queries = "".join("get /dc/cluster/ordersvr/partitions/P%03d\n" % i
                      for i in range(EXPECTED_PARTITIONS)) + "quit\n"
    stdout = command(["docker", "exec", "-i", "dc-saas-zookeeper",
                      "zkCli.sh", "-server", "127.0.0.1:32181"],
                     stdin=queries, timeout=115)
    partitions = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{") and '"partitionId"' in line:
            try:
                partitions.append(json.loads(line))
            except json.JSONDecodeError:
                raise RuntimeError("invalid ZooKeeper partition JSON")
    return partitions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=ORDER_NODES)
    parser.add_argument("--snapshot", help="JSON evidence file (for tests/offline review)")
    args = parser.parse_args()
    try:
        if args.snapshot:
            with open(args.snapshot, encoding="utf-8") as handle:
                evidence = json.load(handle)
        else:
            evidence = live_snapshot()
        problems = issues_for_snapshot(evidence, args.target, require_topology=False)
        if not problems and "partitions" not in evidence:
            evidence["partitions"] = load_topology()
        problems = issues_for_snapshot(evidence, args.target,
                                       require_topology=not bool(problems))
    except (OSError, RuntimeError, ValueError, TypeError, KeyError,
            subprocess.TimeoutExpired) as exc:
        problems = ["unverified evidence: " + str(exc)]
    if problems:
        print("NO-GO Order HA rollout preflight target=" + args.target)
        for problem in problems:
            print(" - " + problem)
        return 2
    print("PRECHECK_PASS target=" + args.target +
          " (NOT rollout authorization: verify synchronized committed replicas, "
          "journal watermarks, epoch and rollback plan separately)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
