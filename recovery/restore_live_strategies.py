#!/usr/bin/env python3
"""Restore strategy sources through candidate.import and current qualification gates."""

import argparse
import json
import os
import time
from pathlib import Path

from strategy_recovery_common import (
    CANDIDATE_IMPORT_TOPIC,
    CANDIDATE_STATUS_TOPIC,
    LIVE_LIST_TOPIC,
    call_gateway,
    parse_env_file,
    resolve_gateway_url,
    validate_seed,
)


TERMINAL_BACKTEST = {"SUCCESS", "FAILED", "SUSPENDED", "CANCELLED", "SKIPPED"}
TERMINAL_GENERATION = {"SUCCESS", "FAILED", "CANCELLED", "SKIPPED"}


def live_strategy(url, api_key, name):
    data = call_gateway(url, api_key, LIVE_LIST_TOPIC, {
        "strategyName": name,
        "status": "ACTIVE",
        "pageSize": 200,
    }, timeout=90)
    for item in data.get("items") or []:
        if item.get("strategyName") == name and str(item.get("status") or "").upper() == "ACTIVE":
            return item
    return None


def active_strategy_map(url, api_key):
    active = {}
    page = 1
    while True:
        data = call_gateway(url, api_key, LIVE_LIST_TOPIC, {
            "status": "ACTIVE",
            "page": page,
            "pageSize": 200,
        }, timeout=90)
        items = data.get("items") or []
        for item in items:
            name = str(item.get("strategyName") or "")
            if name:
                active[name] = item
        total = int(data.get("total") or len(active))
        if not items or len(active) >= total:
            return active
        page += 1


def candidate_state(url, api_key, name, version="v1"):
    return call_gateway(url, api_key, CANDIDATE_STATUS_TOPIC, {
        "strategyName": name,
        "strategyVersion": version,
    }, timeout=90)


def existing_candidate_state(url, api_key, name):
    status = candidate_state(url, api_key, name)
    summary = status.get("summary") or {}
    generation = str(summary.get("generationStatus") or "-").upper()
    backtest = str(summary.get("backtestTaskStatus") or "-").upper()
    candidate = str(summary.get("candidateStatus") or "-").upper()
    if generation not in ("", "-") or backtest not in ("", "-") or candidate not in ("", "-"):
        return "CANDIDATE", status
    return "MISSING", None


def wait_for_terminal(url, api_key, name, version, timeout_seconds, poll_seconds):
    deadline = time.time() + timeout_seconds
    latest = {}
    while time.time() < deadline:
        latest = candidate_state(url, api_key, name, version)
        summary = latest.get("summary") or {}
        generation = str(summary.get("generationStatus") or "-").upper()
        backtest = str(summary.get("backtestTaskStatus") or "-").upper()
        if generation in TERMINAL_GENERATION and generation != "SUCCESS":
            return "GENERATION_FAILED", latest
        if backtest in TERMINAL_BACKTEST:
            return backtest, latest
        time.sleep(poll_seconds)
    return "TIMEOUT", latest


def result_reason(status):
    summary = status.get("summary") or {}
    return (summary.get("backtestFailureReason")
            or summary.get("backtestSuspendReason")
            or summary.get("generationFailureReason")
            or "-")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--env-file", default=".env.prod")
    parser.add_argument("--gw-url", default=os.environ.get("DC_GW_URL", ""))
    parser.add_argument("--api-key", default=os.environ.get("DC_GW_APIKEY", "1"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=int, default=2400)
    parser.add_argument("--poll-seconds", type=int, default=10)
    args = parser.parse_args()

    seed = json.loads(Path(args.seed).read_text(encoding="utf-8"))
    strategies = validate_seed(seed)
    if args.limit > 0:
        strategies = strategies[:args.limit]
    env_values = parse_env_file(args.env_file)
    gateway_url = resolve_gateway_url(args.gw_url, env_values)
    active = active_strategy_map(gateway_url, args.api_key)
    counters = {"active": 0, "existing": 0, "submitted": 0, "published": 0,
                "not_published": 0, "failed": 0, "timeout": 0, "planned": 0}

    for index, strategy in enumerate(strategies, 1):
        name = strategy["strategyName"]
        if name in active:
            counters["active"] += 1
            print("[%d/%d] SKIP ACTIVE %s" % (index, len(strategies), name), flush=True)
            continue
        state, detail = existing_candidate_state(gateway_url, args.api_key, name)
        if state == "CANDIDATE":
            counters["existing"] += 1
            summary = (detail or {}).get("summary") or {}
            print("[%d/%d] SKIP EXISTING %s generation=%s backtest=%s" % (
                index, len(strategies), name,
                summary.get("generationStatus") or "-",
                summary.get("backtestTaskStatus") or "-"), flush=True)
            continue
        if args.dry_run:
            counters["planned"] += 1
            print("[%d/%d] PLAN IMPORT %s %s/%s" % (
                index, len(strategies), name, strategy.get("symbol"), strategy.get("scene")), flush=True)
            continue

        response = call_gateway(
            gateway_url,
            args.api_key,
            CANDIDATE_IMPORT_TOPIC,
            strategy["request"],
            timeout=180,
        )
        counters["submitted"] += 1
        version = str(response.get("strategyVersion") or "v1")
        print("[%d/%d] SUBMITTED %s@%s" % (index, len(strategies), name, version), flush=True)
        terminal, status = wait_for_terminal(
            gateway_url, args.api_key, name, version,
            args.timeout_seconds, max(2, args.poll_seconds))
        if terminal == "TIMEOUT":
            counters["timeout"] += 1
            print("[%d/%d] TIMEOUT %s@%s" % (index, len(strategies), name, version), flush=True)
            continue
        if terminal != "SUCCESS":
            counters["failed"] += 1
            print("[%d/%d] FAILED %s@%s stage=%s reason=%s" % (
                index, len(strategies), name, version, terminal, result_reason(status)), flush=True)
            continue
        live = live_strategy(gateway_url, args.api_key, name)
        if live:
            counters["published"] += 1
            print("[%d/%d] PUBLISHED %s@%s" % (
                index, len(strategies), name, live.get("strategyVersion") or version), flush=True)
        else:
            counters["not_published"] += 1
            print("[%d/%d] BACKTEST_SUCCESS_NOT_PUBLISHED %s@%s" % (
                index, len(strategies), name, version), flush=True)

    print("SUMMARY " + " ".join("%s=%d" % item for item in counters.items()))
    if counters["failed"] or counters["timeout"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
