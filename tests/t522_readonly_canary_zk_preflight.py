#!/usr/bin/env python3
"""Read-only canary ZooKeeper preflight; this does NOT certify Common RSA/READY."""
import argparse
import re
import subprocess
import sys

ROW = re.compile(r"^(P[0-9]{3})\|([0-9]+)\|([A-Za-z0-9_.-]+)\|([A-Za-z0-9_.-]+)\|"
                 r"(STRICT_QUORUM|LOCAL_DURABLE)\|(RECOVERING|READY|PREPARING)$")


def check(output, service):
    if "Node does not exist:" in output or "KeeperErrorCode" in output:
        raise ValueError("NAMESPACE_OR_MANIFEST_MISSING")
    lines = [s.strip() for s in output.splitlines()]
    if not any(re.fullmatch(r"NPC1\|[1-9][0-9]*", line) for line in lines):
        raise ValueError("MISSING_NPC1_MANIFEST")
    found = {}
    for line in lines:
        m = ROW.fullmatch(line)
        if m:
            if m.group(1) in found:
                raise ValueError("DUPLICATE_PARTITION")
            found[m.group(1)] = m
    if len(found) != 256:
        raise ValueError("EXPECTED_256_PARTITIONS_GOT_" + str(len(found)))
    for i in range(256):
        name = "P%03d" % i
        m = found.get(name)
        if not m:
            raise ValueError("MISSING_PARTITION_" + name)
        if {m.group(3), m.group(4)} != {service + "A", service + "B"}:
            raise ValueError("WRONG_ORIGINAL_MEMBERS_" + name)
    return 256


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--container", required=True)
    p.add_argument("--namespace", required=True)
    p.add_argument("--service", choices=("OrderSvr", "TradeSvr"), required=True)
    args = p.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", args.container):
        p.error("invalid container")
    if not re.fullmatch(r"/otc/[A-Za-z0-9_.-]+/(order|trade)", args.namespace):
        p.error("expected isolated /otc/<run-id>/(order|trade)")
    if args.namespace.endswith("/order") != (args.service == "OrderSvr"):
        p.error("service namespace mismatch")
    command = ["docker", "exec", "-i", args.container, "zkCli.sh",
               "-server", "127.0.0.1:2181"]
    try:
        proc = subprocess.run(command, input="get " + args.namespace + "/manifest\nquit\n",
                              text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=20)
        count = check(proc.stdout, args.service)
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        print("NO-GO:T522_CANARY_ZK_BOOTSTRAP:" + str(e))
        return 2
    print("T522_MANIFEST_STRUCTURE_ONLY=%d; NOT_RSA_VERIFIED; NOT_READY; NOT_HA_PASS" % count)
    return 0


if __name__ == "__main__":
    sys.exit(main())