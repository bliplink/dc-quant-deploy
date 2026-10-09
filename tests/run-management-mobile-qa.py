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
if script not in ('management-mobile-acceptance.js', 'management-platform-approval-acceptance.js', 'management-robot-control-acceptance.js'):
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
command = ["docker", "exec", "-i"]
for key in mapping:
    command.extend(["-e", key])  # Docker inherits the value from the caller environment
command.extend([runner, "bash", "-lc",
                "NODE_PATH=/runner/node_modules node /runner/" + script])
print("[management-mobile-qa] exercising isolated tenant", fixture["location"], flush=True)
result = subprocess.run(command, env={**os.environ, **mapping}, check=False)
if result.returncode != 0:
    raise SystemExit('[management-mobile-qa] FAIL; browser test exited with code ' + str(result.returncode))
