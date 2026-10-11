#!/usr/bin/env python3
"""Persist a fresh, read-only 256/256 + ten-tenant Order SIGKILL preflight."""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
OUTPUT = Path(os.environ.get("ORDER_10_FAULT_PREFLIGHT", "/tmp/order10-preflight.json"))
ENV = os.environ.copy()
ENV["ORDER_CLUSTER_VERIFY_LEARNERS"] = "true"
ENV["ORDER_CLUSTER_DATA_ROOT"] = os.environ.get(
    "DEPLOY_ROOT", "/path/that/must/be/real") + "/data"

def execute(argv, env=None, timeout=180):
    return subprocess.run(argv, text=True, capture_output=True, check=True,
                          env=env, timeout=timeout)

def main():
    if "cluster-dev-local-" not in os.environ.get("ORDERSVR_TAG", ""):
        raise RuntimeError("requires locked local Demo image")
    verified = execute(["bash", str(ROOT / "verify-order-cluster-state-host.sh")],
                       env=ENV, timeout=180)
    stdout = verified.stdout
    required = (
        "partitions=256 ready=256",
        "primaries={'OrderSvrB': 256}",
        "replicas={'OrderSvrA': 256, 'OrderSvrC': 256}",
        "snapshot_sets_equal=256 verify_learners=True",
        "[order-cluster-verify] PASS:",
    )
    for marker in required:
        if marker not in stdout:
            raise RuntimeError("Order cluster preflight missing: " + marker)
    audit_env = ENV.copy()
    audit_env["DEMO_TENANT_EXPECT"] = "10"
    audit_env["DEMO_TENANT_AUDIT_OUTPUT"] = str(OUTPUT.with_suffix(".tenant-audit.json"))
    audit = execute(["python3", str(ROOT / "check-demo-tenants-readonly.py")],
                    env=audit_env, timeout=90)
    if "PASS_10_TENANT_SNAPSHOT" not in audit.stdout:
        raise RuntimeError("tenants/robots/order books not healthy")
    report = {
        "checkedUtc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "ready": 256, "primaryB": 256, "replicaAC": 256,
        "snapshotConsistent": 256, "tenants": 10,
        "status": "PASS",
        "scope": "isolated Mac Demo only; Order B primary all partitions",
        "orderVerifier": stdout,
        "tenantAuditPath": audit_env["DEMO_TENANT_AUDIT_OUTPUT"],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n")
    print("[order-ten-preflight] PASS 256/256 READY, snapshots, A+C hot, 10 tenants; %s" %
          OUTPUT, flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("[order-ten-preflight] FAIL: " + repr(exc), file=sys.stderr)
        sys.exit(1)
