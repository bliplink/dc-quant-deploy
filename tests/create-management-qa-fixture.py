#!/usr/bin/env python3
"""Create one isolated, fully traded QA tenant and persist credentials outside Git.

Run with the private deployment .env sourced. No credentials appear in stdout.
"""
import importlib.util
import json
import os
from pathlib import Path
import tempfile

if os.environ.get('MANAGEMENT_QA_CONFIRM') != 'YES':
    raise SystemExit('Set MANAGEMENT_QA_CONFIRM=YES to explicitly create one test tenant')

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("trial_e2e", root / "run-auto-tenant-trading-e2e.py")
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)
qa.main()

target = Path(os.environ.get(
    "MANAGEMENT_QA_FIXTURE",
    "/Users/kong/.opentradingcore/management-qa-fixture.json",
))
target.parent.mkdir(parents=True, exist_ok=True)
with tempfile.NamedTemporaryFile(
    mode="w", dir=target.parent, prefix=".management-qa-", delete=False
) as handle:
    os.fchmod(handle.fileno(), 0o600)
    json.dump({
        "location": qa.LOCATION,
        "admin_username": "tenantadmin",
        "admin_password": qa.ADMIN_PASSWORD,
        "trader_username": qa.TRADER,
        "trader_password": qa.TRADER_PASSWORD,
    }, handle)
    staged = Path(handle.name)
os.replace(staged, target)
os.chmod(target, 0o600)
print("[management-fixture] isolated tenant ready location=" + qa.LOCATION, flush=True)
print("[management-fixture] credentials saved securely on host; no secrets printed")
