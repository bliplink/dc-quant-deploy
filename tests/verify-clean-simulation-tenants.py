#!/usr/bin/env python3
"""Register ten tenants through Manager and settle funded browser market orders in each."""
import json
import sys
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


sys.path.insert(0, str(ROOT / "scripts"))
import simulation_tenants


def main():
    generation = os.environ["SIMULATION_GENERATION"]
    if os.environ.get("GITHUB_ACTIONS") != "true" or not re.fullmatch(r"sim-demo-\d{8}-\d{6}", generation):
        raise RuntimeError("Expected a freshly installed hosted simulation")
    actual = subprocess.check_output(["docker", "inspect", "-f",
                                      '{{index .Config.Labels "com.docker.compose.project"}}',
                                      "dc-saas-mysql"], text=True).strip()
    if actual != generation:
        raise RuntimeError("Tenant test selected a different deployment")
    base = Path(os.environ["RUNNER_TEMP"]) / "t554-install"
    receipt = json.loads((base / "installation.json").read_text())
    locations = receipt["tenants"]
    applications = json.loads((base / generation / "demo-tenant-applications.json").read_text())
    if len(applications) != 10 or simulation_tenants.funded(locations) != 10:
        raise RuntimeError("The installer did not leave ten funded makers quoting")
    for original, location in zip(applications, locations):
        repeated = simulation_tenants.submit(original)
        if repeated.get("approved_location") != location or not repeated.get("idempotent"):
            raise RuntimeError("Repeated tenant provisioning changed its approved identity")
    for i, location in enumerate(locations):
        audit = Path(os.environ["RUNNER_TEMP"]) / ("simulation-browser-" + location)
        audit.mkdir(mode=0o700)
        env = {**os.environ, "SIMULATION_ORIGIN": "http://127.0.0.1:18088",
               "DEMO_LOCATION": location, "AUDIT_DIR": str(audit)}
        subprocess.run(["node", str(ROOT / "tests/public-simulation-maker-browser.cjs")],
                       env=env, check=True, timeout=420)
        print(f"{i+1}/10 tenants settled market open and close in both directions", flush=True)
    if simulation_tenants.funded(locations) != 10:
        raise RuntimeError("At least one funded maker stopped quoting during the browser test")
    print("Ten funded tenants and forty settled market orders verified", flush=True)


if __name__ == "__main__":
    main()
