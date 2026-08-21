#!/usr/bin/env python3
"""Shared helpers for live-strategy backup and candidate-import recovery."""

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


BACKUP_TOPIC = "dc.ind.workbench.live.strategy.backup.export"
CANDIDATE_IMPORT_TOPIC = "dc.ind.strategy.candidate.import"
CANDIDATE_STATUS_TOPIC = "dc.ind.strategy.candidate.status.query"
LIVE_LIST_TOPIC = "dc.ind.workbench.live.strategy.list.query"


def parse_env_file(path):
    values = {}
    if not path:
        return values
    env_path = Path(path)
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def resolve_gateway_url(explicit_url, env_values):
    if explicit_url:
        return explicit_url
    host = env_values.get("GATEWAY_HOST") or "127.0.0.1"
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    port = env_values.get("GATEWAY_PORT") or "3002"
    return "http://%s:%s/" % (host, port)


def call_gateway(url, api_key, method, content, timeout=180, attempts=4):
    payload = json.dumps({
        "serverName": "INDSvr",
        "method": method,
        "content": content,
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    last_error = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "apikey": api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8", "replace"))
            if result.get("code") != 0:
                raise RuntimeError(json.dumps(result, ensure_ascii=False))
            return result.get("data") or {}
        except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as error:
            last_error = error
            if attempt < attempts:
                time.sleep(attempt * 2)
    raise last_error


def object_value(value):
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def sha256_base64(value):
    import base64
    return hashlib.sha256(base64.b64decode(value.encode("ascii"))).hexdigest()


def atomic_write_json(path, value):
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)


def validate_seed(seed):
    if seed.get("packageVersion") != "candidate_import_recovery_seed_v2":
        raise ValueError("unsupported recovery seed packageVersion")
    policy = seed.get("safetyPolicy") or {}
    if policy.get("directLiveRegistryRestore") is not False:
        raise ValueError("recovery seed must forbid direct live-registry restore")
    if policy.get("requireCandidateImport") is not True:
        raise ValueError("recovery seed must require candidate.import")
    plan = seed.get("submissionPlan") or {}
    if plan.get("endpointTopic") != CANDIDATE_IMPORT_TOPIC:
        raise ValueError("recovery endpoint must be %s" % CANDIDATE_IMPORT_TOPIC)
    strategies = seed.get("strategies")
    if not isinstance(strategies, list) or not strategies:
        raise ValueError("recovery seed contains no strategies")
    names = set()
    for strategy in strategies:
        name = str(strategy.get("strategyName") or "").strip()
        if not name or name in names:
            raise ValueError("strategy names must be present and unique: %s" % name)
        names.add(name)
        request = strategy.get("request") or {}
        if request.get("strategyName") != name:
            raise ValueError("request strategyName mismatch: %s" % name)
        if request.get("developmentMode") != "IMPORT":
            raise ValueError("developmentMode must be IMPORT: %s" % name)
        source = request.get("javaSourceBase64") or ""
        if not source:
            raise ValueError("Java source is missing: %s" % name)
        if strategy.get("sourceSha256") != sha256_base64(source):
            raise ValueError("Java source checksum mismatch: %s" % name)
    expected = int((seed.get("summary") or {}).get("activeStrategyCount") or 0)
    if expected != len(strategies):
        raise ValueError("active strategy count does not match strategy entries")
    return strategies
