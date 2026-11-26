#!/usr/bin/env python3
"""Inspect one tenant or queue its normal AdminSvr migration on the original Mac demo."""
import argparse
import json
import re
import subprocess
from pathlib import Path


def run(*args, input_text=None):
    return subprocess.run(args, input=input_text, text=True, capture_output=True,
                          check=True, timeout=20).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generation", type=Path)
    parser.add_argument("location")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    generation = args.generation.resolve(strict=True)
    if not re.fullmatch(r"mac-demo-[0-9]{8}-[0-9]{6}", generation.name):
        parser.error("expected a Mac demo generation directory")
    if not re.fullmatch(r"[A-Z0-9]{6}", args.location):
        parser.error("expected one six-character tenant")
    for name in ("adminsvr", "robotsvr", "mysql"):
        config = json.loads(run("docker", "inspect", "dc-saas-" + name))[0]
        labels = config["Config"]["Labels"]
        if (not config["State"]["Running"] or labels.get("com.docker.compose.project") != generation.name
                or labels.get("com.docker.compose.project.environment_file") != str(generation / "demo.env")
                or labels.get("com.docker.compose.service") != name):
            parser.error(f"{name} belongs to a different deployment or is stopped")
        if args.apply and name != "mysql":
            if ("PUBLIC_SIMULATION_FUNDED_MAKERS=true" not in config["Config"]["Env"]
                    or labels.get("dc.simulation.funded-maker") != "1"):
                parser.error(f"{name} requires the funded-maker candidate and simulation opt-in")
    def sql(statement):
        return run("docker", "exec", "-i", "dc-saas-mysql", "sh", "-c",
                   'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -BN dc', input_text=statement)
    joins = """dc_tenant_liquidity_bootstrap j
        JOIN dc_tenant t ON t.location=j.location AND t.source_application_id=j.application_id
        JOIN dc_tenant_application a ON a.application_id=j.application_id"""
    tenant = f"j.location='{args.location}'"
    if args.apply:
        changed = sql(f"""UPDATE {joins} SET j.status='PENDING',j.step='RETIRE_INTERNAL',
            j.attempts=0,j.next_attempt_time=NULL,j.update_time=NOW(3) WHERE {tenant}
            AND t.status='TRIAL' AND t.trade_enabled=1 AND (t.trial_end_time IS NULL OR t.trial_end_time>=NOW(3))
            AND a.status='APPROVED' AND LENGTH(TRIM(a.reviewer_id))>0
            AND j.status='COMPLETE' AND j.step='DONE' AND j.lease_owner IS NULL
            AND j.funding_confirmed=1 AND j.funding_request_id=CONCAT('TENANT_TRIAL_LIQUIDITY_',LOWER(j.application_id))
            AND (j.tape_enabled=0 OR (j.tape_funding_confirmed=1 AND j.maker_user_id<>j.tape_user_id))
            AND (SELECT COUNT(*) FROM dc_tenant_robot r WHERE r.location=j.location AND r.api_user_id=j.maker_user_id)=1
            AND EXISTS (SELECT 1 FROM dc_tenant_robot r WHERE r.location=j.location AND r.api_user_id=j.maker_user_id
                AND r.hedge_enabled=0 AND r.robot_id=CONCAT('trial-liquidity-',r.security_id));
            SELECT ROW_COUNT();""")
        print("Jobs queued:", changed)
    state = sql(f"""SELECT j.location,j.status,j.step,
        IF(j.funding_request_id=CONCAT('PUBLIC_SIM_MAKER_',LOWER(j.application_id)),'public','internal'),
        j.funding_confirmed,j.tape_funding_confirmed,COALESCE(j.last_error_code,'-')
        FROM {joins} WHERE {tenant}""")
    if not state:
        parser.error("no bootstrap belonging to this tenant application")
    print("tenant\tstatus\tstep\tbook\tmaker funded\ttape funded\terror")
    print(state)
    if args.apply and changed == "0":
        _, status, step, book, *_ = state.split("\t")
        if book != "public" and step not in ("RETIRE_INTERNAL", "DRAIN_INTERNAL"):
            parser.error("tenant did not meet migration preconditions")
        if status in ("FAILED", "NEEDS_RECONCILIATION"):
            parser.error("tenant requires reconciliation before continuing")


if __name__ == "__main__":
    main()
