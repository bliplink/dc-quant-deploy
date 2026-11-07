#!/usr/bin/env python3
"""Read-only proof that an actual Admin/Robot container received opt-in credentials.

Never logs credential values. Does not login, fund, mutate DB, or start containers.
"""
import argparse
import json
import re
import subprocess


def validate_admin_env(values, require_enabled=True, require_tape=False):
    """Use only property presence/length; no credential payloads in errors."""
    env = dict(item.split("=", 1) for item in values if "=" in item)
    errors = []
    if require_enabled and env.get("TRIAL_LIQUIDITY_BOOTSTRAP_ENABLED") != "true":
        errors.append("ADMIN_BOOTSTRAP_DISABLED")
    if require_enabled and len(env.get("TRIAL_LIQUIDITY_MASTER_KEY", "")) < 32:
        errors.append("ADMIN_BOOTSTRAP_MASTER_KEY_ABSENT_OR_TOO_SHORT")
    if env.get("TRIAL_LIQUIDITY_DEMO_RETRY_ENABLED", "false").lower() == "true":
        errors.append("ADMIN_UNSAFE_AMBIGUOUS_FUNDING_RETRY_ENABLED")
    if require_tape and env.get("TRIAL_LIQUIDITY_TAPE_ENABLED") != "true":
        errors.append("ADMIN_TAPE_DISABLED")
    return errors


def validate_robot_env(values):
    env = dict(item.split("=", 1) for item in values if "=" in item)
    problems = []
    for name in ("ROBOT_GATEWAY_USER", "ROBOT_GATEWAY_PASSWORD",
                 "ROBOT_RUNTIME_LOCATION", "ROBOT_RUNTIME_USER_ID",
                 "ROBOT_RUNTIME_API_KEY", "ROBOT_RUNTIME_API_SECRET"):
        if not env.get(name):
            problems.append("ROBOT_REQUIRED_ENV_MISSING:" + name)
    return problems


def inspect_env(container):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", container):
        raise ValueError("INVALID_CONTAINER_NAME")
    proc = subprocess.run(["docker", "inspect", container, "--format",
                           "{{json .Config.Env}}"], capture_output=True, text=True,
                          timeout=15)
    if proc.returncode:
        raise RuntimeError("INSPECT_UNAVAILABLE")
    try:
        result = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        raise RuntimeError("INSPECT_ENV_INVALID_JSON")
    if not isinstance(result, list) or not all(isinstance(x, str) for x in result):
        raise RuntimeError("INSPECT_ENV_INVALID_SHAPE")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-container", required=True)
    parser.add_argument("--robot-container")
    parser.add_argument("--require-tape", action="store_true")
    args = parser.parse_args()
    problems = []
    try:
        problems.extend(validate_admin_env(inspect_env(args.admin_container),
                                           require_tape=args.require_tape))
        if args.robot_container:
            problems.extend(validate_robot_env(inspect_env(args.robot_container)))
    except (ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        problems.append(str(error))
    for problem in problems:
        print("T536_TRIAL_RUNTIME_NO_GO:" + problem)
    if problems:
        return 2
    print("T536_TRIAL_RUNTIME_ENV_PASS (presence-only, not credentials or funding proof)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())