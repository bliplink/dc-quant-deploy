#!/usr/bin/env python3
"""Build the deterministic local pre-admission queue from a live seed and v4 results."""

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def qualification_reason(row):
    if row is None:
        return "realistic_backtest_missing"
    if int(row.get("oosPass") or 0) != 1:
        return "oos_not_passed"
    if int(row.get("tradeCount") or 0) < 20:
        return "too_few_trades"
    if float(row.get("profitFactor") or 0) < 1.20:
        return "profit_factor_too_low"
    if float(row.get("maxDrawdownPct") or 999) > 0.15:
        return "drawdown_too_high"
    if float(row.get("feeAdjustedValidatePnl") or 0) <= 0:
        return "fee_adjusted_validate_not_positive"
    if float(row.get("feeAdjustedForwardPnl") or 0) <= 0:
        return "fee_adjusted_forward_not_positive"
    total_pnl = row.get("totalPnl")
    if total_pnl is None:
        total_pnl = row.get("validatePnl")
    total_pnl = float(total_pnl or 0)
    forward_contribution = (
        float(row.get("feeAdjustedForwardPnl") or 0) / total_pnl
        if total_pnl > 0 else 0
    )
    if forward_contribution < float(row.get("minForwardContribution") or 0.20):
        return "forward_contribution_too_low"
    return "qualified"


def result_key(name, version, symbol, text):
    return (
        str(name or "").strip().lower(),
        str(version or "").strip().lower(),
        str(symbol or "").strip().upper(),
        str(text or "").strip().lower(),
    )


def main():
    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, default=base / "live-strategy-seed-20261009.json")
    parser.add_argument("--qualification-rows", type=Path,
                        default=base / "qualification-rows-20261009.jsonl")
    parser.add_argument("--output", type=Path,
                        default=base / "local-strategy-queue-20261009.json")
    args = parser.parse_args()

    seed = json.loads(args.seed.read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in args.qualification_rows.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_key = {
        result_key(row.get("strategyName"), row.get("strategyVersion"),
                   row.get("symbol"), row.get("text")): row
        for row in rows
    }
    items = []
    for strategy in seed.get("strategies") or []:
        key = result_key(
            strategy.get("strategyName"),
            strategy.get("sourceStrategyVersion"),
            strategy.get("symbol"),
            strategy.get("text"),
        )
        row = by_key.get(key)
        reason = qualification_reason(row)
        item = {
            "strategyName": strategy.get("strategyName"),
            "strategyVersion": strategy.get("sourceStrategyVersion"),
            "symbol": strategy.get("symbol"),
            "scene": strategy.get("scene"),
            "text": strategy.get("text"),
            "baselineQualified": reason == "qualified",
            "baselineReason": reason,
            "baselineMetrics": row or {},
        }
        items.append(item)
    unqualified = [item for item in items if not item["baselineQualified"]]
    reasons = Counter(item["baselineReason"] for item in items)
    queue = {
        "packageVersion": "local_codex_pre_admission_queue_v1",
        "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "sourceSeed": str(args.seed.resolve()),
        "sourceQualificationRows": str(args.qualification_rows.resolve()),
        "policy": {
            "executionModelVersion": "v4_non_overlapping_walk_forward",
            "sceneWindowDays": {
                "range@15m": [90, 30, 14],
                "breakout@15m": [120, 20, 10],
                "reversal@15m": [120, 20, 10],
                "default": [120, 30, 14],
            },
            "minTrades": 20,
            "minProfitFactor": 1.20,
            "maxDrawdownPct": 0.15,
            "requirePositiveFeeAdjustedValidatePnl": True,
            "requirePositiveFeeAdjustedForwardPnl": True,
            "minForwardContribution": 0.20,
            "productionWrite": False,
        },
        "summary": {
            "activeCount": len(items),
            "qualifiedCount": len(items) - len(unqualified),
            "queuedCount": len(unqualified),
            "reasonCounts": dict(sorted(reasons.items())),
        },
        "items": unqualified,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(queue["summary"], ensure_ascii=False, indent=2))
    print("queue=" + str(args.output.resolve()))


if __name__ == "__main__":
    main()
