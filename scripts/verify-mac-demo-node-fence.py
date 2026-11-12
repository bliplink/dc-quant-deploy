#!/usr/bin/env python3
"""Exercise a live node lease expiry and the existing Docker restart policy."""
import argparse
from collections import Counter
from datetime import timedelta
import fcntl
import json
import math
import os
from pathlib import Path
import re
import runpy
import subprocess
import tempfile
import time
import zlib


HERE = Path(__file__).resolve().parent
ROLL = runpy.run_path(str(HERE / "roll-mac-demo-voter.py"))
CAPACITY = runpy.run_path(str(HERE / "verify-mac-demo-robot-capacity.py"))
FRESH, ROBOT = ROLL["FRESH"], ROLL["ROBOT_TRAFFIC"]
inspect, read, run = ROLL["inspect"], FRESH["read"], FRESH["run"]


def control_lease_ttl(path, kind):
    key = re.escape(kind + ".common.control.leaseTtlMs")
    values = re.findall(r"^" + key + r"=([1-9][0-9]*)$", path.read_text(), re.M)
    if len(values) != 1 or not 1000 <= int(values[0]) <= 60000:
        raise RuntimeError("Expected one bounded actual Common node write-lease setting")
    return int(values[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generation", type=Path)
    parser.add_argument("service", choices=("order", "trade"))
    parser.add_argument("slot", choices=("A", "B"))
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    root = args.generation.resolve(strict=True)
    if root.parent != FRESH["LOCAL"].resolve() or not re.fullmatch(r"mac-demo-\d{8}-\d{6}", root.name):
        parser.error("Use the exact original Mac Demo generation directory")
    if not 120 <= args.timeout <= 3600:
        parser.error("Use a recovery observation window of 120 to 3600 seconds")
    os.umask(0o077)
    with (root.parent / ".mac-demo-fresh.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        CAPACITY["require_strict_demo"](root)
        exercise(root, args.service, args.slot, args.timeout)


def exercise(root, kind, slot, timeout):
    generation, service = root.name, FRESH["SERVICES"][kind]
    peer = "A" if slot == "B" else "B"
    node = f"{generation}-{kind}-{slot.lower()}-hostready"
    survivor = f"{generation}-{kind}-{peer.lower()}-hostready"
    namespace = f"/otc/{generation}/{kind}"
    port = FRESH["env_pairs"](root / "demo.env")["ZOOKEEPER_PORT"]
    release = FRESH["env_pairs"](root / "common-release.env")
    ttl = control_lease_ttl(root / "common/config-hostready" / kind / slot / "application.properties", kind)
    if not port.isdigit():
        raise RuntimeError("Expected bounded live Common lease and ZooKeeper settings")

    def query(command, missing=None):
        result = subprocess.run(["docker", "exec", "-i", "dc-saas-zookeeper", "zkCli.sh", "-server",
                                 f"127.0.0.1:{port}"], input=command + "\nquit\n", capture_output=True,
                                text=True, timeout=35)
        if result.returncode == 0:
            return result.stdout
        if missing and result.returncode == 1 and f"Node does not exist: {missing}" in result.stderr.splitlines():
            return None
        raise RuntimeError("The exact active ZooKeeper observation failed")

    def census():
        value = query("get " + namespace + "/manifest")
        generations = re.findall(r"^NPC1\|([1-9][0-9]*)$", value, re.M)
        if len(generations) != 1:
            raise RuntimeError("Expected one exact Common manifest generation")
        return int(generations[0]), ROLL["parse_manifest"](value)

    def lease(member):
        path = namespace + "/leases/" + member
        value = query("stat " + path, path)
        owners = [] if value is None else re.findall(r"^ephemeralOwner\s*=\s*(0x[0-9a-fA-F]+)\s*$", value, re.M)
        if len(owners) != 1 or not int(owners[0], 16):
            raise RuntimeError("Expected the exact live physical voter session")
        return int(owners[0], 16)

    def home_ready(rows):
        return len(rows) == 256 and all(
            row["state"] == "READY" and row["policy"] == "STRICT_QUORUM"
            and row["primary"] == service + ("A" if int(p[1:]) < 128 else "B")
            and row["replica"] == service + ("B" if int(p[1:]) < 128 else "A")
            for p, row in rows.items())

    def robot_identity():
        value = inspect(ROBOT["ROBOT"])
        if not value or not value["State"]["Running"]:
            raise RuntimeError("The existing live Robot is unavailable")
        return [value["Id"], value["State"]["StartedAt"], value["RestartCount"]]

    initial_generation, initial = census()
    old, healthy = inspect(node), inspect(survivor)
    witness = f"{generation}-{kind}-witness"
    if not home_ready(initial):
        raise RuntimeError("The exercise must begin at all 256 strict Home positions")
    for name in (node, survivor, witness):
        value = inspect(name)
        if (not value or not value["State"]["Running"]
                or value["Config"]["Labels"].get("otc.mac.demo.generation") != generation
                or ROLL["common_sha"](name, service) != release["common_sha256"]):
            raise RuntimeError("Expected the three exact verified Common processes")
    if old["HostConfig"]["RestartPolicy"]["Name"] != "on-failure":
        raise RuntimeError("The original Docker on-failure policy must already be installed")
    original_session, peer_session = lease(service + slot), lease(service + peer)
    if original_session == peer_session:
        raise RuntimeError("The two physical voters must have independent sessions")
    order = [f"{generation}-order-{s}-hostready" for s in ("a", "b")]
    trade = [f"{generation}-trade-{s}-hostready" for s in ("a", "b")]
    output = Path(tempfile.mkdtemp(prefix=f"node-fence-{kind}-{slot.lower()}-", dir=root))
    record = {"status": "NO_GO", "generation": generation, "service": service, "slot": slot,
              "original_id": old["Id"], "image": old["Image"], "original_pid": old["State"]["Pid"],
              "original_restarts": old["RestartCount"], "original_session": original_session,
              "survivor_id": healthy["Id"], "survivor_session": peer_session, "initial": initial,
              "lease_ttl_ms": ttl, "pause_seconds": math.ceil(ttl / 1000) + 3,
              "common_sha256": release["common_sha256"], "transitions": []}

    def publish(stage):
        record["stage"] = stage
        pending = output / "evidence.tmp"
        pending.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        pending.replace(output / "evidence.json")
        print(f"[mac-demo node fence] {service}{slot} {stage} {output}", flush=True)

    paused = False
    try:
        record["robot_identity"] = robot_identity()
        def robot_partition(location):
            key = f"{location}\x1f4\x1fBTCUSDT" if kind == "order" else location
            return f"P{zlib.crc32(key.encode()) % 256:03d}"
        before = ROBOT["wait_traffic"](order, trade, ROBOT["utc_now"]() - timedelta(minutes=3),
                    prefer_location=lambda tenant: initial[robot_partition(tenant)]["primary"] == service + slot)
        location = before["location"]
        record["robot_before_fault"] = before
        partition = robot_partition(location)
        record["robot_partition_before_fault"] = {"partition": partition, **initial[partition]}
        started = ROBOT["utc_now"]()
        record["fault_started_at"] = started.isoformat()
        publish("before_pause")
        run("docker", "pause", old["Id"], capture=True, timeout=15)
        paused = True
        time.sleep(record["pause_seconds"])
        record["session_after_lease_expiry"] = lease(service + slot)
        if record["session_after_lease_expiry"] != original_session:
            raise RuntimeError("ZooKeeper session retired before the isolated node-lease observation")
        publish("write_lease_expired_original_session_still_live")
        run("docker", "unpause", old["Id"], capture=True, timeout=15)
        paused = False
        local = {}
        deadline = time.monotonic() + timeout
        previous = None
        startup_ready_at = None
        stable_generation = None
        stable_since = None
        while time.monotonic() < deadline:
            current = inspect(node)
            manifest_generation, rows = census()
            summary = sorted(Counter((r["state"], r["policy"]) for r in rows.values()).items())
            for p, row in rows.items():
                if row["state"] == "READY" and row["policy"] == "LOCAL_DURABLE_ASYNC" and row["primary"] == service + peer:
                    local.setdefault(p, row)
            if summary != previous:
                record["transitions"].append({"at": ROBOT["utc_now"]().isoformat(), "positions": summary})
                previous = summary
                publish("observing_automatic_restart_and_recovery")
            returned = current and current["State"]["Running"] and current["RestartCount"] > old["RestartCount"]
            if returned and startup_ready_at != current["State"]["StartedAt"]:
                logs = subprocess.run(["docker", "logs", "--since", current["State"]["StartedAt"], node],
                                      capture_output=True, text=True, check=True, timeout=30)
                text = logs.stdout + logs.stderr
                if (f"Started {service}" in text
                        and f"COMMON_GATEWAY_DISCOVERY_CERTIFIED service={service} node={service}{slot} " in text):
                    startup_ready_at = current["State"]["StartedAt"]
            complete = returned and startup_ready_at == current["State"]["StartedAt"] and home_ready(rows)
            if not complete or stable_since is None or stable_generation != manifest_generation:
                stable_since = time.monotonic() if complete else None
                stable_generation = manifest_generation
            if stable_since is not None and time.monotonic() - stable_since >= 10:
                routing_ready = True
                if manifest_generation > initial_generation:
                    marker = (f"COMMON_GATEWAY_CERTIFIED_PARTITION_ROUTING_PASS service={service} "
                              f"partitions=256 manifestGeneration={manifest_generation} ")
                    for name in (node, survivor):
                        logs = subprocess.run(["docker", "logs", "--since", started.isoformat(), name],
                                              capture_output=True, text=True, check=True, timeout=30)
                        routing_ready = routing_ready and marker in logs.stdout + logs.stderr
                if routing_ready:
                    break
            time.sleep(2)
        else:
            raise RuntimeError("The existing supervisor did not return all strict Home positions in time")
        if (current["Id"] != old["Id"] or current["Image"] != old["Image"]
                or current["State"]["Pid"] == old["State"]["Pid"]
                or inspect(survivor)["Id"] != healthy["Id"] or lease(service + peer) != peer_session
                or any(rows[p]["epoch"] < row["epoch"] for p, row in initial.items())
                or ROLL["common_sha"](node, service) != release["common_sha256"]):
            raise RuntimeError("Automatic return changed the pinned physical process or regressed an Epoch")
        record["returned_session"] = lease(service + slot)
        if record["returned_session"] in (original_session, peer_session):
            raise RuntimeError("The returned voter did not obtain its own fresh physical session")
        strict_at = ROBOT["utc_now"]()
        record["strict_home"] = rows
        record["return_restarts"] = current["RestartCount"]
        record["return_started_at"] = current["State"]["StartedAt"]
        record["strict_home_at"] = strict_at.isoformat()
        record["recovery_seconds"] = (strict_at - started).total_seconds()
        publish("strict_home_recovered")
        event_lines = read("docker", "events", "--since", str(int(started.timestamp())), "--until",
                           str(math.ceil(strict_at.timestamp())), "--filter", "container=" + old["Id"],
                           "--format", "{{json .}}")
        events = []
        for line in event_lines.splitlines():
            event = json.loads(line)
            if event.get("Action") in ("die", "start", "pause", "unpause"):
                events.append({"action": event["Action"], "time_nano": event.get("timeNano"),
                               "exit_code": event.get("Actor", {}).get("Attributes", {}).get("exitCode")})
        record["docker_events"] = events
        if not any(e["action"] == "die" and e["exit_code"] == "78" for e in events):
            raise RuntimeError("The original Docker process did not actually exit through Common code 78")
        logs = subprocess.run(["docker", "logs", "--since", started.isoformat(), node],
                              capture_output=True, text=True, check=True, timeout=30)
        text = logs.stdout + logs.stderr
        if "FATAL_COMMON_NODE_EPOCH_FENCED exiting JVM (78)" not in text:
            raise RuntimeError("The original process has no Common whole-node fence diagnostic")
        (output / "fence-diagnostics.txt").write_text("\n".join(
            line for line in text.splitlines() if line.startswith(("COMMON_NODE_IRRECOVERABLE_FENCE", "FATAL_COMMON_NODE_EPOCH_FENCED"))) + "\n")
        # A fast return may span fewer than two ordinary Robot cycles.
        # Keep the physical recovery timestamp and extend only the audit.
        remaining = 120 - (ROBOT["utc_now"]() - started).total_seconds()
        if remaining > 0:
            publish("observing_robot_across_fault_and_return")
            time.sleep(remaining)
        observation_until = ROBOT["utc_now"]()
        record["robot_observation_until"] = observation_until.isoformat()
        record["robot_loop"] = ROBOT["rounds"](location, started, observation_until)
        quotes, requests, commits, fills = ROBOT["snapshot"](order, trade, started, strict_at)
        during = {"location": location, "quote_requests": sorted((s, q) for t, s, q in quotes if t == location),
                  "tape_requests": sorted(q for t, q in requests if t == location),
                  "tape_execution_ids": [e for t, e in fills if t == location],
                  "local_trade_commits": sorted((p, e, s) for t, p, e, s in commits if t == location)}
        if not during["quote_requests"]:
            raise RuntimeError("The same Robot has no new quote requests during recovery")
        after = ROBOT["wait_traffic"](order, trade, strict_at, location,
                    previous_quotes=before["quote_requests"] + during["quote_requests"])
        record["robot_during_recovery"], record["robot_after_return"] = during, after
        executions = before["tape_execution_ids"] + during["tape_execution_ids"] + after["tape_execution_ids"]
        if len(executions) != len(set(executions)) or robot_identity() != record["robot_identity"]:
            raise RuntimeError("A Robot restart or repeated execution invalidates the continuous fault proof")
        for traffic in (during, after):
            traffic["posting_event_ids"] = ROBOT["require_posting_pairs"](traffic)
        code, financial, attempts = CAPACITY["reconcile_financial_cursor"]()
        record["financial_cursor"], record["financial_checks"] = financial, attempts
        if code:
            raise RuntimeError("Balances and positions did not reconcile after automatic node return")
        eligible = {p: row for p, row in local.items() if rows[p]["epoch"] > row["epoch"]}
        returned = ROLL["physical_hashes"](node, service, slot, peer, eligible, rows)
        survived = ROLL["physical_hashes"](survivor, service, peer, peer, eligible, rows)
        if returned != survived:
            raise RuntimeError("An observed retired LOCAL WAL or recovery snapshot differs between voters")
        record["observed_local_positions"] = local
        record["verified_immutable_local_partitions"] = len(eligible)
        record["immutable_physical_hashes"] = {"returned": returned, "survivor": survived}
        final_node = inspect(node)
        if (census() != (manifest_generation, rows) or robot_identity() != record["robot_identity"]
                or not final_node or not final_node["State"]["Running"]
                or final_node["State"]["StartedAt"] != current["State"]["StartedAt"]
                or final_node["RestartCount"] != current["RestartCount"]
                or lease(service + slot) != record["returned_session"]
                or lease(service + peer) != peer_session):
            raise RuntimeError("The final certified census or Robot identity changed during reconciliation")
        record["status"] = "PASS_DOCKER_NODE_FENCE_LIVE_ROBOT_FINANCIAL"
        publish("complete")
    except BaseException as failure:
        record["failure_type"] = type(failure).__name__
        if isinstance(failure, RuntimeError):
            record["failure"] = str(failure)
        publish("failed")
        raise
    finally:
        value = inspect(old["Id"])
        if paused and value and value["State"]["Paused"]:
            run("docker", "unpause", old["Id"], capture=True, timeout=15)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error) if isinstance(error, (OSError, RuntimeError)) else "Node-fence observation failed. Inspect its saved evidence.")
