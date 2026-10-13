#!/usr/bin/env python3
"""Submit explicitly selected, locally qualified repairs for server revalidation."""

import argparse
import json
import os
from pathlib import Path

from restore_live_strategies import live_strategy, wait_for_terminal
from strategy_recovery_common import (
    CANDIDATE_IMPORT_TOPIC,
    call_gateway,
    parse_env_file,
    resolve_gateway_url,
)
from summarize_local_strategy_batches import evaluate


def qualified_rows(summary_paths):
    selected = {}
    for path in summary_paths:
        package = json.loads(path.read_text(encoding="utf-8"))
        for row in package.get("results") or []:
            if row.get("executionError"):
                continue
            gate = evaluate(row.get("metrics") or {})
            if gate["qualified"]:
                selected[row["strategyName"]] = row
    return selected


def selected_repairs(seed, rows, names):
    by_name = {
        item["strategyName"]: item
        for item in seed.get("strategies") or []
    }
    selected = []
    for name in names:
        if name not in rows:
            raise ValueError("strategy is not locally qualified: " + name)
        if name not in by_name:
            raise ValueError("strategy is missing from repair seed: " + name)
        item = by_name[name]
        metrics_version = str((rows[name].get("metrics") or {}).get("strategyVersion") or "")
        seed_version = str(item.get("sourceStrategyVersion") or "")
        if metrics_version and seed_version and metrics_version != seed_version:
            raise ValueError("result/source version mismatch for %s: %s != %s" % (
                name, metrics_version, seed_version))
        selected.append(item)
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True, action="append")
    parser.add_argument("--strategy", required=True, action="append")
    parser.add_argument("--env-file", default=".env.prod")
    parser.add_argument("--gw-url", default=os.environ.get("DC_GW_URL", ""))
    parser.add_argument("--api-key", default=os.environ.get("DC_GW_APIKEY", "1"))
    parser.add_argument("--timeout-seconds", type=int, default=2400)
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument(
        "--submit", action="store_true",
        help="Actually submit to candidate.import; without this flag only validate and plan.")
    args = parser.parse_args()

    seed = json.loads(args.seed.resolve().read_text(encoding="utf-8"))
    rows = qualified_rows([path.resolve() for path in args.summary])
    repairs = selected_repairs(seed, rows, args.strategy)
    if not args.submit:
        for item in repairs:
            metrics = rows[item["strategyName"]].get("metrics") or {}
            print("PLAN_REVALIDATE %s@%s trades=%s pf=%s" % (
                item["strategyName"], item.get("sourceStrategyVersion"),
                metrics.get("tradeCount"), metrics.get("profitFactor")))
        return

    env_values = parse_env_file(args.env_file)
    gateway_url = resolve_gateway_url(args.gw_url, env_values)
    failed = 0
    for item in repairs:
        name = item["strategyName"]
        response = call_gateway(
            gateway_url, args.api_key, CANDIDATE_IMPORT_TOPIC,
            item["request"], timeout=180)
        version = str(response.get("strategyVersion") or "v1")
        print("SUBMITTED %s@%s" % (name, version), flush=True)
        terminal, status = wait_for_terminal(
            gateway_url, args.api_key, name, version,
            args.timeout_seconds, max(2, args.poll_seconds))
        if terminal != "SUCCESS":
            failed += 1
            summary = status.get("summary") or {}
            reason = (summary.get("backtestFailureReason")
                      or summary.get("backtestSuspendReason")
                      or summary.get("generationFailureReason") or "-")
            print("FORMAL_FAILED %s@%s stage=%s reason=%s" % (
                name, version, terminal, reason), flush=True)
            continue
        live = live_strategy(gateway_url, args.api_key, name)
        live_version = str((live or {}).get("strategyVersion") or "")
        state = "PUBLISHED" if live_version == version else "SUCCESS_NOT_PUBLISHED"
        print("FORMAL_%s %s@%s activeVersion=%s" % (
            state, name, version, live_version or "-"), flush=True)
    if failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
