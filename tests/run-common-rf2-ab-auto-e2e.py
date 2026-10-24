#!/usr/bin/env python3
"""Isolated, reproducible REAL Common RF2 A->B->A automatic HA acceptance.

Requires: Docker Compose, prebuilt v19 strict-cutover classes / Common JAR
and generated TEST-ONLY node identities in the source project.
Never touches dc-saas production services. Uses a fresh Compose project,
its own network and volumes; leaves evidence volumes intact after stopping.
REAL test JVMs perform election, recovery, catchup and READY autonomously;
this driver only injects SIGKILL and submits client requests.

Important: solo ACK is LOCAL_DURABLE and advertises possible RPO>0.
DO NOT interpret solo success as zero-loss strict quorum.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

CLASSPATH = "/tmp/common.jar:/tmp/v19:/srv/dc/dc/GW/lib/*"
CLI = "com.opentradingcore.demo.DemoV19TcpClient"


def command(argv, check=True, timeout=30):
    proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, timeout=timeout)
    if check and proc.returncode:
        raise RuntimeError("%r exit=%s\nstdout=%s\nstderr=%s" %
                           (argv, proc.returncode, proc.stdout[-1800:], proc.stderr[-2000:]))
    return proc.stdout


def wait_until(what, predicate, timeout=120):
    until = time.monotonic() + timeout
    last = ""
    while time.monotonic() < until:
        try:
            outcome = predicate()
            if outcome:
                print("AUTO_HA_WITNESS", what, flush=True)
                return
        except (RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
            last = str(exc)[:250]
        time.sleep(2)
    raise RuntimeError("auto HA deadline: %s last=%s" % (what, last))


def decode(text, marker):
    rows = [line.split(marker, 1)[1] for line in text.splitlines() if marker in line]
    if not rows:
        raise ValueError("TCP response missing %r: %s" % (marker, text[-500:]))
    return json.loads(rows[-1])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path,
                        help="source project containing compose.v19-rf2-strict-cutover.yaml")
    parser.add_argument("--project", default="otc-t66-%s" % uuid.uuid4().hex[:9])
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    compose_file = source / "compose.v19-rf2-strict-cutover.yaml"
    if not compose_file.is_file() or not re.fullmatch("[a-z][a-z0-9-]{8,60}", args.project):
        raise RuntimeError("invalid isolated Compose input")
    source_class = source / "target-v19-strict-cutover-compiled" / "com" / "opentradingcore" / "demo" / "DemoV19Rf2AutoStage.class"
    if not source_class.is_file():
        raise RuntimeError("real compiled automatic failover source is absent")
    with tempfile.TemporaryDirectory(prefix="otc-t66-compose-") as tmp:
        override = Path(tmp) / "isolated.yaml"
        override.write_text("name: %s\nnetworks:\n  isolated:\n    name: %s-net\n" % (args.project, args.project))
        compose = ["docker", "compose", "-p", args.project,
                   "-f", str(compose_file), "-f", str(override)]

        def dc(*cmd, **opts):
            return command(compose + list(cmd), **opts)

        def logs(node):
            return dc("logs", "--no-color", "otc-ha-demo-" + node, timeout=18)

        def probe(node, op, *parts):
            return dc("exec", "-T", "otc-ha-demo-" + node.lower(), "java",
                      "-cp", CLASSPATH, CLI, "--isolated", op, node.upper(),
                      *parts, timeout=17)

        def append(node, req, delta, mode, epoch):
            result = None
            for attempt in range(7):
                try:
                    result = decode(probe(node, "append", req, str(delta)), "V19_TCP_APPEND ")
                    break
                except (RuntimeError, ValueError, subprocess.TimeoutExpired):
                    # EXACT SAME requestId on all retries. A timeout may mean
                    # the two WALs were committed and only the ACK was lost.
                    time.sleep(2)
            if result is None:
                raise RuntimeError("bounded client timeout retries exhausted: " + req)
            if (result.get("code") != 0 or result.get("appliedCount") != 1
                    or result.get("durabilityMode") != mode
                    or result.get("epoch") != epoch):
                raise RuntimeError("unsafe client ACK: " + json.dumps(result, sort_keys=True))
            if mode == "AUTO_DEGRADED_LOCAL_DURABLE":
                if result.get("quorumDurable") is not False or result.get("possibleDataLossIfPrimaryPermanentlyLost") is not True:
                    raise RuntimeError("solo ACK falsely advertised zero RPO")
            elif mode == "QUORUM_DURABLE":
                if result.get("quorumDurable") is not True:
                    raise RuntimeError("strict data acknowledgement lacks 2/2 proof")
            print("AUTO_HA_REAL_ACK", json.dumps(
                {k: result.get(k) for k in ("node", "epoch", "committedSeq", "requestId",
                                            "appliedCount", "durabilityMode", "quorumDurable")},
                sort_keys=True), flush=True)
            return result

        def terminate(node):
            cid = dc("ps", "-q", "otc-ha-demo-" + node).strip()
            if not cid:
                raise RuntimeError("not a live data process: " + node)
            command(["docker", "kill", "--signal=SIGKILL", cid], timeout=20)

        def stage(node, marker, epoch):
            # Automatic logs include partition and physical primary between
            # the event name and epoch. Match both on ONE actual log line.
            wait_until("%s %s epoch=%s" % (node, marker, epoch),
                       lambda: any(marker in line and "epoch=" + str(epoch) in line
                                   for line in logs(node).splitlines()), 140)

        def assert_exact_state(expected_seq):
            observed = []
            for name in ("A", "B"):
                status = decode(probe("a", "status") if name == "A"
                                else probe("b", "status"), "V19_TCP_STATUS ")
                observed.append(status)
            fields = ("committedSeq", "distinctRequests", "lastEpoch",
                      "committedPrefixSha256", "stateDigest")
            for f in fields:
                if observed[0].get(f) != observed[1].get(f):
                    raise RuntimeError("WAL diverged on %s: %s vs %s" %
                                       (f, observed[0].get(f), observed[1].get(f)))
            if observed[0]["committedSeq"] != expected_seq or observed[0]["distinctRequests"] != expected_seq:
                raise RuntimeError("missing or duplicate logical mutations")
            print("AUTO_HA_FINAL_STATE_IDENTICAL", json.dumps(
                {f: observed[0][f] for f in fields}, sort_keys=True), flush=True)

        running = False
        try:
            dc("up", "-d", "--no-deps", "otc-ha-zk1", "otc-ha-zk2", "otc-ha-zk3", timeout=90)
            running = True
            dc("up", "-d", "otc-ha-bootstrap", timeout=90)
            bootstrap_id = dc("ps", "-a", "-q", "otc-ha-bootstrap").strip()
            if not bootstrap_id or command(["docker", "wait", bootstrap_id]).strip() != "0":
                raise RuntimeError("fresh ZooKeeper bootstrap did not succeed")
            dc("up", "-d", "--no-deps", "otc-ha-demo-a", "otc-ha-demo-b", timeout=95)
            wait_until("A/B network ready", lambda: "V19_TCP_STATUS " in probe("a", "status"), 65)
            append("a", "t66-accept-01", 7, "QUORUM_DURABLE_SINGLE_HOST_TEST", 1)

            terminate("a")
            stage("b", "V19_RF2_AUTO_DEGRADED_READY", 2)
            append("b", "t66-accept-02", 9, "AUTO_DEGRADED_LOCAL_DURABLE", 2)
            dc("up", "-d", "--no-deps", "otc-ha-demo-a", timeout=70)
            stage("b", "V19_RF2_STRICT_READY_ACTIVATED", 3)
            append("b", "t66-accept-03", 11, "QUORUM_DURABLE", 3)
            assert_exact_state(3)

            terminate("b")
            stage("a", "V19_RF2_AUTO_DEGRADED_READY", 4)
            append("a", "t66-accept-04", 13, "AUTO_DEGRADED_LOCAL_DURABLE", 4)
            dc("up", "-d", "--no-deps", "otc-ha-demo-b", timeout=70)
            stage("a", "V19_RF2_STRICT_READY_ACTIVATED", 5)
            append("a", "t66-accept-05", 17, "QUORUM_DURABLE", 5)
            assert_exact_state(5)

            dc("stop", "otc-ha-demo-a", "otc-ha-demo-b",
               "otc-ha-zk1", "otc-ha-zk2", "otc-ha-zk3", timeout=95)
            dc("up", "-d", "--no-deps", "otc-ha-zk1", "otc-ha-zk2",
               "otc-ha-zk3", timeout=75)
            dc("up", "-d", "--no-deps", "otc-ha-demo-a", "otc-ha-demo-b", timeout=85)
            stage("a", "V19_RF2_STRICT_READY_ACTIVATED", 5)
            append("a", "t66-accept-06", 19, "QUORUM_DURABLE", 5)
            assert_exact_state(6)
            print("AUTO_HA_T66_RF2_TWO_WAY_PASS strictEpochs=1,3,5 soloEpochs=2,4"
                  " physicalJVMs=2 faultDomain=ONE_MAC"
                  " productionTradeOrders=NOT_TESTED"
                  " localAckPossibleRpo=true", flush=True)
        finally:
            if running:
                dc("stop", "otc-ha-demo-a", "otc-ha-demo-b",
                   "otc-ha-zk1", "otc-ha-zk2", "otc-ha-zk3",
                   check=False, timeout=90)
                print("AUTO_HA_STOPPED evidenceVolumesPreserved=true project=" +
                      args.project, flush=True)


if __name__ == "__main__":
    main()
