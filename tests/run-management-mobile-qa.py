#!/usr/bin/env python3
"""Launch authenticated Chromium acceptance against local admin consoles.

Reads credentials from the private host deployment environment and the
QA-only account fixture; never prints secrets or copies them into Git.
"""
import json
import os
from pathlib import Path
import subprocess

credentials = Path(os.environ.get(
    "MANAGEMENT_QA_FIXTURE",
    "/Users/kong/.opentradingcore/management-qa-fixture.json",
))
fixture = json.loads(credentials.read_text(encoding="utf-8"))
for name in ("PLATFORM_ADMIN_USERNAME", "PLATFORM_ADMIN_PASSWORD"):
    if not os.environ.get(name):
        raise SystemExit("missing deployment environment variable: " + name)
script = os.environ.get('MANAGEMENT_QA_SCRIPT', 'management-mobile-acceptance.js')
if script not in ('management-mobile-acceptance.js', 'management-platform-approval-acceptance.js', 'management-robot-control-acceptance.js', 'management-robot-edit-acceptance.js', 'management-robot-create-acceptance.js'):
    raise SystemExit('Unsupported management QA script')
source = Path(__file__).with_name(script)
runner = os.environ.get("E2E_RUNNER_NAME", "dc-saas-web-e2e-runner")
subprocess.run(
    ["docker", "cp", str(source), runner + ":/runner/" + script],
    check=True,
)
mapping = {
    "QA_TENANT_LOCATION": fixture["location"],
    "QA_ADMIN_USERNAME": fixture["admin_username"],
    "QA_ADMIN_PASSWORD": fixture["admin_password"],
    "PLATFORM_ADMIN_USERNAME": os.environ["PLATFORM_ADMIN_USERNAME"],
    "PLATFORM_ADMIN_PASSWORD": os.environ["PLATFORM_ADMIN_PASSWORD"],
    "QA_ONLY_CRUD": os.environ.get("QA_ONLY_CRUD", "0"),
    "QA_ONLY_UI": os.environ.get("QA_ONLY_UI", "0"),
    "QA_DETAIL_ONLY": os.environ.get("QA_DETAIL_ONLY", "0"),
    "QA_VERIFY_ONLY": os.environ.get("QA_VERIFY_ONLY", "0"),
}
if script == 'management-robot-create-acceptance.js' and os.environ.get('MANAGEMENT_QA_CREATE_CONFIRM') != 'YES':
    raise SystemExit('Set MANAGEMENT_QA_CREATE_CONFIRM=YES before creating a disabled QA Robot')
if script == 'management-robot-create-acceptance.js':
    import re
    location = fixture['location']
    if not re.fullmatch(r'[A-Z0-9]{6}', location):
        raise SystemExit('QA tenant location invalid')
    db_user = os.environ.get('MYSQL_USERNAME')
    db_password = os.environ.get('MYSQL_PASSWORD')
    if not db_user or not db_password:
        raise SystemExit('Private DB read-only QA variables missing')
    sql = ("SELECT api_user_id,api_key FROM dc_tenant_robot "
           "WHERE location='" + location + "' AND enabled=1 LIMIT 1")
    proc = subprocess.run(
        ['docker','exec','-e','MYSQL_PWD','dc-saas-mysql','mysql',
         '-u' + db_user,'-N','dc','-e',sql], capture_output=True, text=True,
        env={**os.environ, 'MYSQL_PWD':db_password}, check=False)
    if proc.returncode != 0 or len(proc.stdout.strip().splitlines()) != 1:
        raise SystemExit('QA Robot identity lookup failed')
    parts = proc.stdout.strip().split('\t')
    if len(parts) != 2 or not all(parts):
        raise SystemExit('QA Robot identity incomplete')
    mapping['QA_ROBOT_API_USER_ID'],mapping['QA_ROBOT_API_KEY'] = parts

command = ["docker", "exec", "-i"]
for key in mapping:
    command.extend(["-e", key])  # Docker inherits the value from the caller environment
command.extend([runner, "bash", "-lc",
                "NODE_PATH=/runner/node_modules node /runner/" + script])
print("[management-mobile-qa] exercising isolated tenant", fixture["location"], flush=True)
result = subprocess.run(command, env={**os.environ, **mapping}, check=False)
if result.returncode != 0:
    raise SystemExit('[management-mobile-qa] FAIL; browser test exited with code ' + str(result.returncode))
