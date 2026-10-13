#!/usr/bin/env python3
"""Build an auditable local-backtest seed from reviewed strategy repairs."""

import argparse
import base64
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


PACKAGE_VERSION = re.compile(r"\bpackage\s+[A-Za-z0-9_.]+\.(v\d+)\s*;")


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def source_version(source):
    match = PACKAGE_VERSION.search(source)
    if not match:
        raise ValueError("repair source package must end in .v<number>")
    return match.group(1)


def build_seed(base_seed, manifest, manifest_dir, generated_at=None):
    repaired = []
    by_name = {
        item["strategyName"]: item
        for item in base_seed.get("strategies") or []
    }
    seen = set()
    for repair in manifest.get("repairs") or []:
        name = repair["strategyName"]
        if name in seen:
            raise ValueError("duplicate repair: " + name)
        seen.add(name)
        if name not in by_name:
            raise ValueError("strategy missing from base seed: " + name)
        item = copy.deepcopy(by_name[name])
        request = item["request"]
        source_path = (manifest_dir / repair["source"]).resolve()
        source = source_path.read_text(encoding="utf-8")
        version = source_version(source)
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        previous_version = item.get("sourceStrategyVersion") or ""

        request["javaSourceBase64"] = base64.b64encode(
            source.encode("utf-8")).decode("ascii")
        request["parentVersion"] = previous_version
        request["sourceRef"] = "local-logic-repair:%s:%s" % (version, source_hash[:12])
        request["description"] = repair["description"]
        request["logicSummary"] = repair["logicSummary"]
        if repair.get("parameterSchema") is not None:
            request["parameterSchema"] = repair["parameterSchema"]
        request.setdefault("defaultParameters", {}).update(
            repair.get("defaultParameters") or {})
        request.setdefault("optimizationProfile", {}).update(
            repair.get("optimizationProfile") or {})

        item["sourceStrategyVersion"] = version
        item["sourceSha256"] = source_hash
        item["originalArtifactBase64"] = ""
        item["originalArtifactSha256"] = ""
        item["repairId"] = repair["repairId"]
        item["repairStatus"] = repair.get("status") or "REVIEW_REQUIRED"
        item["repairRationale"] = repair["rationale"]
        item["repairSource"] = str(source_path)
        repaired.append(item)

    timestamp = generated_at or datetime.now(timezone.utc).astimezone().isoformat(
        timespec="seconds")
    return {
        "packageVersion": "local_logic_repair_seed_v1",
        "packageType": "LOCAL_BACKTEST_ONLY",
        "generatedAt": timestamp,
        "sourcePackageVersion": base_seed.get("packageVersion"),
        "safetyPolicy": {
            "productionWrite": False,
            "gateRelaxation": False,
            "forwardWindowOptimization": False,
        },
        "summary": {"strategyCount": len(repaired)},
        "strategies": repaired,
    }


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-seed", type=Path, required=True)
    parser.add_argument(
        "--manifest", type=Path,
        default=here / "strategy-repairs" / "manifest.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_seed(
        load_json(args.base_seed.resolve()),
        load_json(args.manifest.resolve()),
        args.manifest.resolve().parent,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("strategies=%d" % result["summary"]["strategyCount"])
    print("LOGIC_REPAIR_SEED=" + str(args.output.resolve()))


if __name__ == "__main__":
    main()
