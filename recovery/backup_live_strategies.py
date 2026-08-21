#!/usr/bin/env python3
"""Export ACTIVE live strategies as a candidate.import recovery seed."""

import argparse
import os
from datetime import datetime, timezone

from strategy_recovery_common import (
    BACKUP_TOPIC,
    CANDIDATE_IMPORT_TOPIC,
    atomic_write_json,
    call_gateway,
    object_value,
    parse_env_file,
    resolve_gateway_url,
    sha256_base64,
    validate_seed,
)


def latest_active_rows(rows):
    active = {}
    for row in rows or []:
        if str(row.get("status") or "").upper() != "ACTIVE":
            continue
        key = (row.get("strategyName"), row.get("strategyVersion"))
        old = active.get(key)
        if old is None or str(row.get("effectiveTime") or "") > str(old.get("effectiveTime") or ""):
            active[key] = row
    return sorted(active.values(), key=lambda item: (
        str(item.get("symbolScope") or ""),
        str(item.get("scene") or ""),
        str(item.get("strategyName") or ""),
    ))


def build_seed(package):
    if package.get("packageType") != "live_strategy_backup":
        raise ValueError("unexpected INDSvr backup package type")
    active_rows = latest_active_rows(package.get("registryRows"))
    candidates = {
        (row.get("strategyName"), row.get("strategyVersion")): row
        for row in package.get("candidateRows") or []
    }
    strategies = []
    for registry in active_rows:
        key = (registry.get("strategyName"), registry.get("strategyVersion"))
        candidate = candidates.get(key)
        if candidate is None:
            raise ValueError("candidate row is missing for active strategy %s@%s" % key)
        source_base64 = candidate.get("javaSourceContentBase64") or ""
        if not source_base64:
            raise ValueError("Java source is missing for active strategy %s@%s" % key)
        registry_payload = object_value(registry.get("payload"))
        candidate_payload = object_value(candidate.get("payload"))
        parameters = object_value(candidate.get("parametersJson"))
        default_parameters = candidate_payload.get("defaultParameters")
        if not isinstance(default_parameters, dict):
            default_parameters = parameters.get("defaultParams")
        parameter_schema = candidate_payload.get("parameterSchema")
        if not isinstance(parameter_schema, dict):
            parameter_schema = parameters.get("parameterSchema")
        optimization_profile = candidate_payload.get("optimizationProfile")
        if not isinstance(optimization_profile, dict):
            optimization_profile = parameters.get("optimizationProfile")
        symbol = (registry_payload.get("symbol") or registry.get("regenerateSymbol")
                  or registry.get("symbolScope"))
        symbols = registry_payload.get("symbols") or symbol
        text = (registry_payload.get("text") or registry.get("regenerateText")
                or registry.get("textScope") or "15m")
        name, version = key
        source_ref = "recovery:%s:%s@%s" % (
            package.get("exportTime") or "unknown", name, version)
        request = {
            "strategyName": name,
            "parentVersion": "",
            "developmentMode": "IMPORT",
            "scene": registry.get("scene") or candidate.get("scene"),
            "description": registry.get("description") or candidate.get("description") or "Recovered live strategy",
            "sourceRef": source_ref,
            "javaSourceBase64": source_base64,
            "symbol": symbol,
            "symbols": symbols,
            "text": text,
            "logicSummary": candidate.get("logicSummary") or candidate_payload.get("logicSummary") or "",
            "parameterSchema": parameter_schema or {},
            "defaultParameters": default_parameters or {},
            "optimizationProfile": optimization_profile or {},
            "sync": False,
        }
        artifact = candidate.get("artifactContentBase64") or ""
        strategy = {
            "strategyName": name,
            "sourceStrategyVersion": version,
            "symbol": symbol,
            "scene": request["scene"],
            "text": text,
            "sourceEffectiveTime": registry.get("effectiveTime") or "",
            "sourceSha256": sha256_base64(source_base64),
            "originalArtifactSha256": sha256_base64(artifact) if artifact else "",
            "originalArtifactBase64": artifact,
            "submitTopic": CANDIDATE_IMPORT_TOPIC,
            "request": request,
        }
        strategies.append(strategy)
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    seed = {
        "packageVersion": "candidate_import_recovery_seed_v2",
        "packageType": "candidate_import_recovery_seed",
        "generatedAt": generated_at,
        "sourceExportTime": package.get("exportTime") or "",
        "sourceService": package.get("service") or "INDSvr",
        "safetyPolicy": {
            "directLiveRegistryRestore": False,
            "requireCandidateImport": True,
            "requireFreshCompile": True,
            "requireFormalSceneBacktest": True,
            "publishOnlyAfterCurrentGatesPass": True,
        },
        "submissionPlan": {
            "endpointTopic": CANDIDATE_IMPORT_TOPIC,
            "requestPath": "strategies[].request",
            "recommendedMaxParallel": 1,
            "waitForCompileAndBacktestTerminalState": True,
            "autoPublishUsesCurrentProductionGates": True,
        },
        "summary": {
            "activeStrategyCount": len(strategies),
            "embeddedSourceCount": sum(1 for item in strategies if item["request"].get("javaSourceBase64")),
            "embeddedOriginalArtifactCount": sum(1 for item in strategies if item.get("originalArtifactBase64")),
        },
        "strategies": strategies,
    }
    validate_seed(seed)
    return seed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env.prod")
    parser.add_argument("--gw-url", default=os.environ.get("DC_GW_URL", ""))
    parser.add_argument("--api-key", default=os.environ.get("DC_GW_APIKEY", "1"))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    env_values = parse_env_file(args.env_file)
    gateway_url = resolve_gateway_url(args.gw_url, env_values)
    exported = call_gateway(
        gateway_url,
        args.api_key,
        BACKUP_TOPIC,
        {"scope": "live_only", "limit": 2000},
        timeout=180,
    )
    package = exported.get("packageData") or {}
    seed = build_seed(package)
    atomic_write_json(args.output, seed)
    summary = seed["summary"]
    print("Backup completed: active=%d, sources=%d, artifacts=%d, output=%s" % (
        summary["activeStrategyCount"],
        summary["embeddedSourceCount"],
        summary["embeddedOriginalArtifactCount"],
        args.output,
    ))


if __name__ == "__main__":
    main()
