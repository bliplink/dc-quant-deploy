#!/usr/bin/env python3
"""Build a deterministic, sample-aware repair seed for failed live strategies."""

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


EXECUTION_ONLY = {
    "firstStepPct", "stepPct", "fallbackTriggerPct", "fallbackTakePct",
}


def unique(values):
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def candidates(name, value, existing=None):
    values = list(existing or [])
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return unique(values + [value])
    if isinstance(value, int):
        minimum = 1 if any(token in name.lower() for token in ("period", "window", "lookback", "offset")) else 0
        generated = [
            max(minimum, int(round(value * factor)))
            for factor in (0.67, 0.83, 1.0, 1.17, 1.33)
        ]
        return sorted(unique(values + generated))
    if value == 0:
        generated = [0.0]
    else:
        generated = [round(value * factor, 8) for factor in (0.70, 0.85, 1.0, 1.15, 1.30)]
    return sorted(unique(values + generated))


def sample_floor(scene):
    scene = str(scene or "").lower()
    if scene == "range":
        return 10
    if scene in ("breakout", "reversal"):
        return 20
    return 16


def repair_request(item, reason):
    request = copy.deepcopy(item.get("request") or {})
    defaults = copy.deepcopy(request.get("defaultParameters") or {})
    schema = copy.deepcopy(request.get("parameterSchema") or {})
    definitions = {
        str(row.get("name")): row
        for row in schema.get("parameters") or []
        if row.get("name")
    }
    repaired = []
    for name, value in defaults.items():
        if name in EXECUTION_ONLY or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        definition = copy.deepcopy(definitions.get(name) or {})
        definition["name"] = name
        definition["type"] = "int" if isinstance(value, int) else "double"
        definition["default"] = value
        definition["candidates"] = candidates(name, value, definition.get("candidates"))
        if len(definition["candidates"]) > 1:
            repaired.append(definition)
    schema["parameters"] = repaired
    request["parameterSchema"] = schema

    profile = copy.deepcopy(request.get("optimizationProfile") or {})
    profile.update({
        "mode": "RANDOM_LOCAL",
        "objective": "FEE_ADJUSTED_PROFIT_FIRST",
        "maxCoarseCandidates": 32,
        "maxFineCandidates": 8,
        "topN": 12,
        "minForwardContribution": 0.20,
        "minFitTradesPerSlice": sample_floor(item.get("scene")),
        "randomSeed": int(hashlib.sha256(item["strategyName"].encode("utf-8")).hexdigest()[:12], 16),
        "repairProfileVersion": "sample_aware_v1",
        "repairBaselineReason": reason,
    })
    request["optimizationProfile"] = profile
    return request


def build(seed, batch):
    failed = {
        row["strategyName"]: row
        for row in batch.get("results") or []
        if not row.get("qualified") and not row.get("executionError")
    }
    repaired_seed = copy.deepcopy(seed)
    repaired_items = []
    queue_items = []
    for item in repaired_seed.get("strategies") or []:
        row = failed.get(item.get("strategyName"))
        if not row:
            continue
        item["request"] = repair_request(item, row.get("qualificationReason"))
        repaired_items.append(item)
        queue_items.append({
            "strategyName": item["strategyName"],
            "strategyVersion": item.get("sourceStrategyVersion"),
            "symbol": item.get("symbol"),
            "scene": item.get("scene"),
            "text": item.get("text", "15m"),
            "baselineQualified": False,
            "baselineReason": row.get("qualificationReason"),
            "baselineMetrics": row.get("metrics") or {},
        })
    reason_rank = {
        "too_few_trades": 0,
        "forward_contribution_too_low": 1,
        "fee_adjusted_validate_not_positive": 2,
        "profit_factor_too_low": 3,
        "oos_not_passed": 4,
    }
    queue_items.sort(key=lambda row: (
        reason_rank.get(row.get("baselineReason"), 9),
        -int((row.get("baselineMetrics") or {}).get("oosPass") or 0),
        -int(float((row.get("baselineMetrics") or {}).get("feeAdjustedValidatePnl") or 0) > 0),
        -int(float((row.get("baselineMetrics") or {}).get("feeAdjustedForwardPnl") or 0) > 0),
        -int((row.get("baselineMetrics") or {}).get("tradeCount") or 0),
        -min(10.0, float((row.get("baselineMetrics") or {}).get("profitFactor") or 0)),
        row["strategyName"],
    ))
    repaired_seed["packageVersion"] = "candidate_import_repair_seed_v1"
    repaired_seed["generatedAt"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    repaired_seed["repairPolicy"] = {
        "profileVersion": "sample_aware_v1",
        "productionWrite": False,
        "gateRelaxation": False,
        "selectionData": "fit_only",
        "objective": "FEE_ADJUSTED_PROFIT_FIRST",
        "searchBudget": {"maxCoarseCandidates": 32, "maxFineCandidates": 8},
    }
    repaired_seed["strategies"] = repaired_items
    repaired_seed["summary"] = {"repairCount": len(repaired_items)}
    queue = {
        "packageVersion": "local_codex_strategy_repair_queue_v1",
        "generatedAt": repaired_seed["generatedAt"],
        "policy": repaired_seed["repairPolicy"],
        "summary": {"queuedCount": len(queue_items)},
        "items": queue_items,
    }
    return repaired_seed, queue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--batch-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--queue-output", type=Path, required=True)
    args = parser.parse_args()
    seed = json.loads(args.seed.read_text(encoding="utf-8"))
    batch = json.loads(args.batch_summary.read_text(encoding="utf-8"))
    repaired_seed, queue = build(seed, batch)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.queue_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(repaired_seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.queue_output.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(repaired_seed["summary"], ensure_ascii=False))
    print("REPAIR_SEED=" + str(args.output.resolve()))
    print("REPAIR_QUEUE=" + str(args.queue_output.resolve()))


if __name__ == "__main__":
    main()
