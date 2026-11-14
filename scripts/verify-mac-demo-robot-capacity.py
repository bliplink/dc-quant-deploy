#!/usr/bin/env python3
"""Enroll Demo trials through Manager and measure their real Robot traffic."""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import json
from pathlib import Path
import re
import runpy
import secrets
import shlex
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tests"))
FRESH = runpy.run_path(str(HERE / "mac-demo-fresh.py"))
PRODUCT = runpy.run_path(str(HERE.parent / "tests/test-custom-product-live-e2e.py"))
MEASURE = runpy.run_path(str(HERE / "measure-mac-demo-robot.py"))
from t457_readonly_common_ha_preflight import parse_manifest  # noqa: E402
from check_trial_robot_trade_e2_readonly import query_counts  # noqa: E402


def demo_tenants():
    sql = ("SELECT t.location,COALESCE(CASE WHEN r.runtime_status='RUNNING' AND "
           "(r.runtime_owner IS NULL OR r.runtime_lease_until IS NULL "
           "OR r.runtime_lease_until<=NOW(3)) THEN 'STALE_RUNTIME' "
           "ELSE r.runtime_status END,'MISSING') "
           "FROM dc_tenant t LEFT JOIN dc_tenant_robot r ON r.location=t.location "
           "AND r.robot_id='trial-liquidity-BTCUSDT' "
           "WHERE t.status IN ('ACTIVE','TRIAL') AND r.enabled=1 ORDER BY t.location")
    output = subprocess.check_output(
        ["docker", "exec", "dc-saas-mysql", "sh", "-c",
         'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N dc -e "$1"', "--", sql],
        text=True, timeout=30)
    rows = dict(line.split("\t", 1) for line in output.splitlines())
    if any(not re.fullmatch(r"[A-Z0-9]{6}", location) for location in rows):
        raise RuntimeError("Unexpected active tenant in this Demo generation")
    return rows


def common_release_identity(root):
    release = FRESH["env_pairs"](root / "common-release.env")
    return {"common_revision": release["common_revision"], "common_sha256": release["common_sha256"],
            "client_ack_policy": release.get("client_ack_policy", "STRICT_QUORUM")}


def require_client_ack_policy(root, release):
    selected = FRESH["selected_client_ack_policy"](
        release, release.get("client_ack_policy", "STRICT_QUORUM"))
    names = [f"{root.name}-{service}-{slot}-hostready" for service in ("order", "trade") for slot in "ab"]
    voters = json.loads(subprocess.check_output(["docker", "inspect", *names], text=True, timeout=20))
    if len(voters) != len(names):
        raise RuntimeError("Missing physical voters before measuring Common confirmation policy")
    for voter, name in zip(voters, names):
        labels = voter["Config"]["Labels"]
        if (voter["Name"] != "/" + name or not voter["State"]["Running"]
                or labels.get("dc.common.jar.sha256") != release["common_sha256"]
                or labels.get("otc.common.client_ack_policy", "STRICT_QUORUM") != selected):
            raise RuntimeError("Physical voter identity or client confirmation label differs from this release")
        options = []
        for entry in voter["Config"]["Env"]:
            key, value = entry.split("=", 1)
            if key in {"JAVA_OPTS", "EXTRA_JAVA_OPTS", "JAVA_TOOL_OPTIONS"}:
                options.extend(shlex.split(value))
        property_name = "-Dcommon.certified.clientAckPolicy"
        configured = [option for option in options
                      if option == property_name or option.startswith(property_name + "=")]
        expected = [property_name + "=" + selected]
        if configured != expected and not (selected == "STRICT_QUORUM" and not configured):
            raise RuntimeError("Actual voter JVM confirmation policy differs from the measured release")
    return selected


def require_strict_demo(root, check_space=True):
    active = subprocess.check_output(
        ["docker", "inspect", "-f", '{{index .Config.Labels "com.docker.compose.project"}}',
         "dc-saas-gateway", "dc-saas-mysql", "dc-saas-robotsvr"], text=True, timeout=20).splitlines()
    if root.parent != FRESH["LOCAL"].resolve() or not re.fullmatch(r"mac-demo-\d{8}-\d{6}", root.name):
        raise RuntimeError("Expected a verified local Mac Demo generation")
    release = FRESH["env_pairs"](root / "common-release.env")
    if active != [root.name] * 3 or not FRESH["verified_common_release"](release):
        raise RuntimeError("The exact verified Mac Demo must be active")
    require_client_ack_policy(root, release)
    if FRESH["read"]("uname", "-s") != "Darwin" or FRESH["read"]("docker", "context", "show") != "colima":
        raise RuntimeError("Expected the original Mac Colima context")
    if check_space:
        FRESH["require_docker_space"](min_host_free_bytes=4 * 1024 ** 3)
    port = int(FRESH["env_pairs"](root / "demo.env")["ZOOKEEPER_PORT"])
    generations = {}
    for service in ("order", "trade"):
        command = f"get /otc/{root.name}/{service}/manifest\nquit\n"
        transcript = subprocess.run(
            ["docker", "exec", "-i", "dc-saas-zookeeper", "zkCli.sh", "-server", f"127.0.0.1:{port}"],
            input=command, capture_output=True, text=True, check=True, timeout=30)
        manifest = parse_manifest(transcript.stdout)
        serials = re.findall(r"^NPC1\|([1-9][0-9]*)$", transcript.stdout, re.M)
        if len(serials) != 1:
            raise RuntimeError("Expected one actual Common manifest generation")
        generations[service] = int(serials[0])
        if len(manifest) != 256 or any(row["state"] != "READY" or row["policy"] != "STRICT_QUORUM"
                                       for row in manifest.values()):
            raise RuntimeError(f"Expected all {service} partitions to be strict before increasing load")
    return generations


def enroll(target):
    rows = demo_tenants()
    if len(rows) > target:
        raise RuntimeError("Active tenant count is above this phase. Existing tenants are preserved.")
    while len(rows) < target:
        if len(rows) % 10 == 0:
            FRESH["require_docker_space"](min_host_free_bytes=4 * 1024 ** 3)
        suffix = secrets.token_hex(8)
        request_id = "T554_CAPACITY_" + suffix
        tenant = PRODUCT["ok"]("http://127.0.0.1:49502/httpapi/", "ManagerSvr", "tenantApplication", {
            "action": "SUBMIT", "cid": request_id, "request_id": request_id,
            "organization_name": "T554 Demo Capacity " + suffix,
            "contact_name": "Demo Capacity", "contact_email": f"capacity-{suffix}@acceptance.invalid",
            "expected_users": 4, "admin_password": secrets.token_urlsafe(24),
        })
        previous = rows
        location = tenant.get("approved_location")
        if (tenant.get("status") != "APPROVED" or not isinstance(location, str)
                or not re.fullmatch(r"[A-Z0-9]{6}", location) or location in previous):
            raise RuntimeError("Trial approval did not identify a new Demo tenant")
        expected = set(previous) | {location}
        enrollment_deadline = time.monotonic() + 60
        while True:
            rows = demo_tenants()
            if set(rows) == expected:
                break
            if set(rows) != set(previous):
                raise RuntimeError("Demo Robot membership changed outside the approved enrollment")
            if time.monotonic() >= enrollment_deadline:
                raise RuntimeError("Approved Demo Robot did not appear within 60 seconds")
            time.sleep(0.2)
        if len(rows) % 5 == 0 or len(rows) == target:
            print(f"{len(rows)} of {target} Demo tenants enrolled", flush=True)
    return set(rows)


def reconcile_financial_cursor(max_wait=120):
    deadline = time.monotonic() + max_wait
    attempts = []
    while True:
        result = subprocess.run(
            [sys.executable, str(HERE.parent / "tests/check_certified_trade_financial_cursor.py"),
             "--mysql", "dc-saas-mysql", "--require-predecessors"],
            capture_output=True, text=True, timeout=130)
        report = json.loads(result.stdout)
        attempts.append({"checked_at": datetime.now(timezone.utc).isoformat(),
                         "returncode": result.returncode, "report": report})
        if (result.returncode == 0
                or report.get("reasons") != ["FINANCIAL_CURSOR_DIFFERS_FROM_SOURCE"]
                or time.monotonic() >= deadline):
            return result.returncode, report, attempts
        # Ingestion and financial consumption are separate transactions.
        # Keep the exact equality check and retain each observed lag sample.
        time.sleep(1)


def audit_tape_immediate_terminals(locations, max_age_seconds=30):
    """Query the real Tape accounts; SQL history may omit still-unsettled orders."""
    selected=set(locations)
    if not selected or any(not re.fullmatch(r'[A-Z0-9]{6}', value) for value in selected):
        raise RuntimeError('Expected the exact observed Robot cohort')
    quoted=','.join("'"+value+"'" for value in sorted(selected))
    rows=PRODUCT['readonly_sql'](
        "SELECT location,tape_user_id FROM dc_tenant_liquidity_bootstrap "
        "WHERE status='COMPLETE' AND tape_enabled=1 AND location IN ("+quoted+")")
    actors=dict(rows)
    if set(actors)!=selected or any(not value for value in actors.values()):
        raise RuntimeError('The exact Robot Tape accounts are not available for terminal verification')
    audit={'max_nonterminal_age_seconds':max_age_seconds,'queried_accounts':[], 'aged_nonterminal_orders':[],
           'checked_at':datetime.now(timezone.utc).isoformat()}
    for location,user in sorted(actors.items()):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',user):
            raise RuntimeError('Unexpected Tape account identity')
        sessions=PRODUCT['readonly_sql']("SELECT token FROM dc_users_session WHERE location='"+location+"' AND user_id='"+user+"'")
        orders=None
        for token, in sessions:
            reply=PRODUCT['call']('http://127.0.0.1:49502/httpapi/','OrderSvr','queryOpenOrder',{
                'location':location,'userid':user,'securityid':'BTCUSDT','SecurityID':'BTCUSDT',
                'marketIndicator':'4','maxOrderCount':100},token)
            if reply.get('code')==0:
                orders=reply.get('data');break
        if not isinstance(orders,list):
            raise RuntimeError('Live Tape account open-order query failed')
        if len(orders)>=100:
            raise RuntimeError('Tape terminal audit exceeded the complete bounded query window')
        audit['queried_accounts'].append({'location':location,'user_id':user})
        for order in orders:
            if order.get('Terminal')!='RobotSvr-Tape' or order.get('TimeInForce') not in ('IOC','FOK'):
                continue
            raw=order.get('UpdateTime')
            if not isinstance(raw,str):
                raise RuntimeError('A live Tape immediate order has no age timestamp')
            stamp=datetime.strptime(raw,'%Y-%m-%d %H:%M:%S.%f')
            age=(datetime.now()-stamp).total_seconds()
            if age>=max_age_seconds:
                audit['aged_nonterminal_orders'].append({
                    'location':location,'user_id':user,'order_id':order.get('OrderID'),
                    'client_order_id':order.get('ClOrdID'),'status':order.get('OrdStatus'),
                    'time_in_force':order.get('TimeInForce'),'age_seconds':round(age,3)})
    audit['passed']=not audit['aged_nonterminal_orders']
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generation", type=Path)
    parser.add_argument("target", choices=(10, 50, 200), type=int)
    args = parser.parse_args()
    root = args.generation.resolve(strict=True)
    if root.parent != FRESH["LOCAL"].resolve():
        parser.error("Use the original Mac Demo directory")
    with (root.parent / ".mac-demo-fresh.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require_strict_demo(root)
        locations = enroll(args.target)
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            rows = demo_tenants()
            if rows.keys() == locations and all(state == "RUNNING" for state in rows.values()):
                break
            time.sleep(10)
        until = datetime.now(timezone.utc)
        since = until - timedelta(seconds=300)
        resource_samples = []
        control_before = None
        if rows.keys() == locations and all(state == "RUNNING" for state in rows.values()):
            control_before = require_strict_demo(root)
            print("All selected Robots are running. Measuring a five-minute steady window.", flush=True)
            since = datetime.now(timezone.utc)
            with MEASURE["sample_resources"](root.name) as resource_samples:
                time.sleep(300)
                until = datetime.now(timezone.utc)
        output = root / f"robot-steady-{args.target}-{until:%H%M%S}.json"
        # Preserve the actual window and resource evidence before any later
        # control, log or financial validation can fail.
        with output.open("x") as evidence:
            json.dump({"generation": root.name, "target_tenants": args.target,
                       "from": since.isoformat(), "until": until.isoformat(),
                       "resource_samples": resource_samples,
                       "control_generation_before": control_before,
                       "runtime_status_at_admission": rows,
                       "status": "MEASUREMENT_COMPLETE_VALIDATION_PENDING", "passed": False},
                      evidence, indent=2)
            evidence.write("\n")
        control_after = require_strict_demo(root, check_space=False)
        sample = MEASURE["measure"](root.name, since, until, locations)
        sample["common_release"] = common_release_identity(root)
        sample["target_tenants"] = args.target
        sample["resource_samples"] = resource_samples
        sample["control_generation_before"] = control_before
        sample["control_generation_after"] = control_after
        sample["runtime_status"] = demo_tenants()
        sample["posting_window"] = query_counts("dc-saas-mysql", 5)
        financial_code, financial_report, financial_checks = reconcile_financial_cursor()
        sample["financial_cursor"] = financial_report
        sample["financial_cursor_checks"] = financial_checks
        sample["tape_terminal_audit"] = audit_tape_immediate_terminals(locations)
        posting = sample["posting_window"]
        sample["passed"] = (sample["runtime_status"].keys() == locations
                            and control_before == control_after
                            and all(state == "RUNNING" for state in sample["runtime_status"].values())
                            and all(gap < 300 for gap in sample["largest_tape_fill_gap_seconds_by_tenant"].values())
                            and any(point.get("containers") for point in resource_samples)
                            and posting["posting_locations"] >= args.target
                            and posting["bad_posting_pairs"] == 0 and financial_code == 0
                            and sample["tape_terminal_audit"]["passed"])
        pending = output.with_suffix(".pending")
        with pending.open("x") as evidence:
            json.dump(sample, evidence, indent=2)
            evidence.write("\n")
        pending.replace(output)
        print(f"{'PASS' if sample['passed'] else 'NO_GO'} {output}", flush=True)
        if not sample["passed"]:
            sys.exit(2)


if __name__ == "__main__":
    main()
