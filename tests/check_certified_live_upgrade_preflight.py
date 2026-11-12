#!/usr/bin/env python3
"""T547: fail-closed *existing live* certified Order/Trade redeploy preflight.

This is release orchestration, NOT a replacement for Common HA or any signed
ACK/recovery proof. No mutations, no ZooKeeper writes, no log secrets exposed.
Fresh install (no running managed peers) remains a separate pathway; a live
cluster is blocked until genuine automatic rolling+recovery acceptance exists.
"""
import argparse
import json
import re
import subprocess
import sys


def read(*command, timeout=20):
    response = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if response.returncode:
        raise RuntimeError("DOCKER_READ_FAILED:" + command[1])
    return response.stdout + (response.stderr if command[:2] == ("docker", "logs") else "")


def info(name):
    response = subprocess.run(["docker", "inspect", name],
                              capture_output=True, text=True, timeout=12)
    if response.returncode:
        if "No such" in response.stderr or "No such" in response.stdout:
            return None
        raise RuntimeError("DOCKER_INSPECT_FAILED")
    rows = json.loads(response.stdout)
    if len(rows) != 1:
        raise RuntimeError("INVALID_CONTAINER_CENSUS")
    return rows[0]


def property_value(raw, key):
    rows = [line.split("=", 1)[1].strip() for line in raw.splitlines()
            if line.strip().startswith(key + "=")]
    return rows[0] if len(rows) == 1 else None


def assess_pair(scope, metadata):
    """Only truly absent/exited pairs can enter the distinct cold-start path.

    Even apparently healthy running processes remain NO_GO without physically
    certified A/B rolling E2->E3 proof. There is currently no such proof in the
    managed SaaS release process. Future work must add an actual verifier, not
    an operator bypass boolean.
    """
    statuses = [x.get("State", {}).get("Status") if x else "absent"
                for x in metadata]
    if not any(status == "running" for status in statuses):
        return [], "COLD_START_NOT_HA_PROVEN"
    problems = ["LIVE_" + scope.upper() + "_ROLLING_HA_PROOF_NOT_INSTALLED"]
    if statuses != ["running", "running"]:
        problems.append(scope.upper() + "_NODES_NOT_BOTH_RUNNING")
    return problems, "LIVE_REDEPLOY_BLOCKED"


def assess_runtime(scope, conf, digest, error_log):
    prefix = scope.lower() + ".common.nodeRuntime."
    failures = []
    for key, required in (("enabled", "true"), ("phase", "READY"),
                          ("automaticRecovery", "true")):
        if property_value(conf, prefix + key) != required:
            failures.append(scope.upper() + "_CERTIFIED_" + key.upper() + "_NOT_READY")
    if not re.fullmatch("[0-9a-f]{64}", digest or ""):
        failures.append(scope.upper() + "_COMMON_JAR_SHA_UNVERIFIED")
    if ("Common poisoned primary Epoch" in error_log or
            "COMMON_CERTIFIED_PARTITION_BUSINESS_DENIED" in error_log or
            "COMMON_CERTIFIED_CENSUS_STARTUP_TIMEOUT" in error_log):
        failures.append(scope.upper() + "_CERTIFIED_WRITES_OR_RECOVERY_DENIED")
    return failures


def verify_pair(scope, names):
    nodes = [info(name) for name in names]
    problems, condition = assess_pair(scope, nodes)
    status = {"condition": condition, "nodes": {}}
    if condition == "COLD_START_NOT_HA_PROVEN":
        for name, entry in zip(names, nodes):
            status["nodes"][name] = (entry or {}).get("State", {}).get("Status", "absent")
        return problems, status
    digest = []
    for name, entry in zip(names, nodes):
        status["nodes"][name] = (entry or {}).get("State", {}).get("Status", "absent")
        if not entry or entry.get("State", {}).get("Status") != "running":
            continue
        try:
            root = "/srv/dc/dc/" + scope + "Svr"
            conf = read("docker", "exec", name, "cat", root + "/config/application.properties")
            jars = read("docker", "exec", name, "sh", "-c",
                        "find " + root + "/lib -maxdepth 1 -type f "
                        "-name 'com.app.common*.jar' -print").splitlines()
            if len(jars) != 1:
                raise RuntimeError("EXACT_COMMON_JAR_MISSING")
            sha = read("docker", "exec", name, "sha256sum", jars[0]).split()[0]
            digest.append(sha)
            logs = read("docker", "logs", "--since", "30s", name, timeout=22)
            problems.extend(assess_runtime(scope, conf, sha, logs))
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
            problems.append(scope.upper() + "_LIVE_NODE_PROOF_UNAVAILABLE")
    if len(digest) == 2 and len(set(digest)) != 1:
        problems.append(scope.upper() + "_COMMON_JAR_SHA_MISMATCH")
    return problems, status


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--order-enabled", choices=("true", "false"), default="false")
    args.add_argument("--trade-enabled", choices=("true", "false"), default="false")
    args.add_argument("--order-a", default="dc-saas-ordersvr")
    args.add_argument("--order-b", default="dc-saas-ordersvr-b")
    args.add_argument("--trade-a", default="dc-saas-tradesvr")
    args.add_argument("--trade-b", default="dc-saas-tradesvr-b")
    opt = args.parse_args()
    problems = []
    details = {}
    for scope, enabled, names in [
        ("Order", opt.order_enabled, [opt.order_a, opt.order_b]),
        ("Trade", opt.trade_enabled, [opt.trade_a, opt.trade_b]),
    ]:
        if enabled != "true":
            details[scope] = {"condition": "CLUSTER_DISABLED"}
            continue
        try:
            issues, report = verify_pair(scope, names)
            details[scope] = report
            problems.extend(issues)
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
            problems.append(scope.upper() + "_CENSUS_UNAVAILABLE")
    result = {"status": "NO_GO_EXISTING_LIVE_CLUSTER_UPGRADE" if problems
              else "COLD_START_ONLY_OR_CLUSTER_DISABLED",
              "production_ha_verified": False, "services": details,
              "reasons": sorted(set(problems))}
    print(json.dumps(result, ensure_ascii=False))
    return 2 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
