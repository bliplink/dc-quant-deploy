#!/usr/bin/env python3
"""Register ten tenants through Manager and settle funded browser market orders in each."""
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
from urllib import request, error

ROOT = Path(__file__).resolve().parents[1]


def submit(application):
    payload = json.dumps({"serverName": "ManagerSvr", "method": "tenantApplication", "content": application}).encode()
    req = request.Request("http://127.0.0.1:18088/httpapi/", data=payload, headers={"Content-Type": "application/json"})
    for attempt in range(30):
        try:
            with request.urlopen(req, timeout=15) as response:
                reply = json.load(response)
            if reply.get("code") == 0:
                return reply["data"]
            if "not Online" not in str(reply.get("msg")):
                raise RuntimeError(f"Tenant application rejected with code {reply.get('code')}")
        except (error.URLError, TimeoutError):
            pass
        time.sleep(2)
    raise RuntimeError("Manager did not answer the tenant application")


def funded(locations):
    if len(set(locations)) != 10 or any(not re.fullmatch(r"[A-Z0-9]{6}", loc) for loc in locations):
        raise ValueError("Expected ten distinct approved locations")
    items = ",".join("'" + loc + "'" for loc in locations)
    sql = f"""SELECT COUNT(DISTINCT j.location) FROM dc_tenant_liquidity_bootstrap j
      JOIN dc_tenant_robot r ON r.location=j.location AND r.api_user_id=j.maker_user_id
      WHERE j.location IN ({items}) AND j.status='COMPLETE' AND j.step='DONE' AND j.funding_confirmed=1
      AND j.funding_request_id=CONCAT('PUBLIC_SIM_MAKER_',LOWER(j.application_id))
      AND r.security_id='BTCUSDT' AND r.enabled=1 AND r.runtime_status='RUNNING'
      AND r.hedge_enabled=0 AND r.open_order_count>=2 AND r.last_heartbeat_time>=NOW()-INTERVAL 30 SECOND"""
    p = subprocess.run(["docker", "exec", "-i", "dc-saas-mysql", "sh", "-c",
                        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -BN dc'],
                       input=sql, text=True, capture_output=True, check=True)
    return int(p.stdout.strip())


def main():
    generation = os.environ["SIMULATION_GENERATION"]
    if os.environ.get("GITHUB_ACTIONS") != "true" or not re.fullmatch(r"sim-demo-\d{8}-\d{6}", generation):
        raise RuntimeError("Expected a freshly installed hosted simulation")
    actual = subprocess.check_output(["docker", "inspect", "-f",
                                      '{{index .Config.Labels "com.docker.compose.project"}}',
                                      "dc-saas-mysql"], text=True).strip()
    if actual != generation:
        raise RuntimeError("Tenant test selected a different deployment")
    locations = []
    for i in range(10):
        identity = f"{generation}-{i}"
        application = {"action": "SUBMIT", "cid": identity, "request_id": identity,
                       "organization_name": f"Simulation acceptance {i}", "contact_name": "Acceptance",
                       "contact_email": f"{identity}@acceptance.invalid", "expected_users": 3,
                       "requested_symbols": ["BTCUSDT"], "admin_password": secrets.token_urlsafe(24)}
        result = submit(application)
        if result.get("status") != "APPROVED":
            raise RuntimeError("Tenant application did not reach APPROVED")
        repeated = submit(application)
        if repeated.get("application_id") != result["application_id"] or not repeated.get("idempotent"):
            raise RuntimeError("Repeated tenant application lost its original identity")
        locations.append(result["approved_location"])
    until = time.monotonic() + 900
    while (count := funded(locations)) < 10:
        if time.monotonic() >= until:
            raise RuntimeError(f"Only {count} of ten funded makers are actively quoting")
        time.sleep(5)
    for i, location in enumerate(locations):
        audit = Path(os.environ["RUNNER_TEMP"]) / ("simulation-browser-" + location)
        audit.mkdir(mode=0o700)
        env = {**os.environ, "SIMULATION_ORIGIN": "http://127.0.0.1:18088",
               "DEMO_LOCATION": location, "AUDIT_DIR": str(audit)}
        subprocess.run(["node", str(ROOT / "tests/public-simulation-maker-browser.cjs")],
                       env=env, check=True, timeout=420)
        print(f"{i+1}/10 tenants settled market open and close in both directions", flush=True)
    if funded(locations) != 10:
        raise RuntimeError("At least one funded maker stopped quoting during the browser test")
    print("Ten funded tenants and forty settled market orders verified", flush=True)


if __name__ == "__main__":
    main()
