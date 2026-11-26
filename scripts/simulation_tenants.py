"""Provision the ten simulated tenants through the installed gateway and check funded Robot readiness."""
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
from urllib import request, error


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
        except error.HTTPError as response:
            if response.code not in (502, 503, 504):
                raise RuntimeError(f"Gateway returned HTTP {response.code} during tenant provisioning") from None
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
      AND j.tape_enabled=1 AND j.tape_funding_confirmed=1
      AND j.funding_request_id=CONCAT('PUBLIC_SIM_MAKER_',LOWER(j.application_id))
      AND r.security_id='BTCUSDT' AND r.enabled=1 AND r.runtime_status='RUNNING'
      AND r.hedge_enabled=0 AND r.open_order_count>=2 AND r.last_heartbeat_time>=NOW()-INTERVAL 30 SECOND"""
    p = subprocess.run(["docker", "exec", "-i", "dc-saas-mysql", "sh", "-c",
                        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -BN dc'],
                       input=sql, text=True, capture_output=True, check=True)
    return int(p.stdout.strip())


def enroll(generation_dir):
    generation = generation_dir.name
    if not re.fullmatch(r"sim-demo-\d{8}-\d{6}", generation):
        raise ValueError("Expected the installed simulation generation")
    actual = subprocess.check_output(["docker", "inspect", "-f",
                                      '{{index .Config.Labels "com.docker.compose.project"}}',
                                      "dc-saas-mysql"], text=True).strip()
    if actual != generation:
        raise RuntimeError("Tenant provisioning selected a different deployment")
    private = generation_dir / "demo-tenant-applications.json"
    if not private.exists():
        applications = []
        for index in range(1, 11):
            identity = f"{generation}-{index:02}"
            applications.append({"action": "SUBMIT", "cid": identity, "request_id": identity,
                                 "organization_name": f"Simulation Tenant {index:02}", "contact_name": "Demo Operator",
                                 "contact_email": f"{identity}@simulation.invalid", "expected_users": 3,
                                 "requested_symbols": ["BTCUSDT"], "admin_password": secrets.token_urlsafe(24)})
        tmp = private.with_suffix(".tmp")
        with open(tmp, "w", opener=lambda p, flags: os.open(p, flags, 0o600)) as f:
            json.dump(applications, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, private)
    if private.is_symlink() or private.stat().st_mode & 0o077:
        raise RuntimeError("Tenant application credentials must be private")
    applications = json.loads(private.read_text())
    if [row["request_id"] for row in applications] != [f"{generation}-{i:02}" for i in range(1, 11)]:
        raise RuntimeError("Tenant applications do not belong to this generation")
    locations = []
    for application in applications:
        result = submit(application)
        if result.get("status") != "APPROVED":
            raise RuntimeError("Tenant application did not reach APPROVED")
        locations.append(result["approved_location"])
    until = time.monotonic() + 900
    while (count := funded(locations)) != 10:
        if time.monotonic() >= until:
            raise RuntimeError(f"{count} of ten funded makers are actively quoting; provisioning can be retried")
        time.sleep(5)
    return locations
