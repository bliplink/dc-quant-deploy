#!/usr/bin/env python3
"""Merge local backtest batches and re-evaluate the production admission gates."""

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


EXECUTION_MODEL = "v4_non_overlapping_walk_forward"


def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def evaluate(metrics):
    metrics = metrics or {}
    total_pnl = metrics.get("totalPnl")
    if total_pnl is None:
        # Older LocalBacktestCli output omitted totalPnl. In SIMSvr v4 the
        # aggregate total used by this gate is the aggregate validate PnL.
        total_pnl = metrics.get("validatePnl")
    total_pnl = number(total_pnl)
    fee_forward = number(metrics.get("feeAdjustedForwardPnl"))
    min_contribution = number(metrics.get("minForwardContribution"), 0.20)
    contribution = fee_forward / total_pnl if total_pnl > 0 else 0.0
    checks = [
        ("realistic_backtest_missing", metrics.get("executionModelVersion") != EXECUTION_MODEL),
        ("oos_not_passed", int(metrics.get("oosPass") or 0) != 1),
        ("too_few_trades", int(metrics.get("tradeCount") or 0) < 20),
        ("profit_factor_too_low", number(metrics.get("profitFactor")) < 1.20),
        ("drawdown_too_high", number(metrics.get("maxDrawdownPct"), 999.0) > 0.15),
        ("fee_adjusted_validate_not_positive", number(metrics.get("feeAdjustedValidatePnl")) <= 0),
        ("fee_adjusted_forward_not_positive", fee_forward <= 0),
        ("forward_contribution_too_low", contribution < min_contribution),
    ]
    failures = [reason for reason, failed in checks if failed]
    return {
        "qualified": not failures,
        "qualificationReason": failures[0] if failures else "qualified",
        "failedGates": failures,
        "forwardContribution": round(contribution, 6),
        "minForwardContribution": min_contribution,
        "totalPnl": total_pnl,
    }


def compact(row, source_batch):
    metrics = row.get("metrics") or {}
    gate = evaluate(metrics)
    return {
        "strategyName": row.get("strategyName"),
        "strategyVersion": metrics.get("strategyVersion"),
        "symbol": row.get("symbol"),
        "scene": row.get("scene"),
        "sourceBatch": source_batch,
        **gate,
        "metrics": {
            key: metrics.get(key)
            for key in (
                "fitWindowDays", "validateWindowDays", "forwardWindowDays",
                "sliceCount", "tradeCount", "profitFactor", "maxDrawdownPct",
                "validatePnl", "forwardPnl", "feeAdjustedValidatePnl",
                "feeAdjustedForwardPnl", "oosPass", "overfitReason",
            )
        },
    }


def load_results(path):
    package = json.loads(path.read_text(encoding="utf-8"))
    return package.get("results") or []


def build_summary(baseline_path, corrected_path):
    selected = {}
    for row in load_results(baseline_path):
        selected[row["strategyName"]] = compact(row, baseline_path.name)
    for row in load_results(corrected_path):
        selected[row["strategyName"]] = compact(row, corrected_path.name)
    rows = sorted(selected.values(), key=lambda row: (
        str(row.get("symbol")), str(row.get("scene")), str(row.get("strategyName"))))
    reasons = Counter(row["qualificationReason"] for row in rows)
    qualified = [row for row in rows if row["qualified"]]
    near_passes = sorted(
        (row for row in rows if len(row["failedGates"]) == 1),
        key=lambda row: (row["failedGates"][0], row["strategyName"]),
    )
    return {
        "packageVersion": "local_codex_authoritative_strategy_summary_v1",
        "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "productionWrite": False,
        "policy": {
            "executionModelVersion": EXECUTION_MODEL,
            "sceneWindowDays": {
                "range@15m": [90, 30, 14],
                "breakout@15m": [120, 20, 10],
                "reversal@15m": [120, 20, 10],
                "default": [120, 30, 14],
            },
            "minTrades": 20,
            "minProfitFactor": 1.20,
            "maxDrawdownPct": 0.15,
            "minForwardContribution": 0.20,
        },
        "summary": {
            "strategyCount": len(rows),
            "qualifiedCount": len(qualified),
            "nearPassCount": len(near_passes),
            "qualificationReasonCounts": dict(sorted(reasons.items())),
        },
        "qualified": qualified,
        "nearPasses": near_passes,
        "results": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-summary", type=Path, required=True)
    parser.add_argument("--corrected-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = build_summary(args.baseline_summary.resolve(), args.corrected_summary.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary["summary"], ensure_ascii=False, indent=2))
    print("SUMMARY=" + str(args.output.resolve()))


if __name__ == "__main__":
    main()
