#!/usr/bin/env python3
"""Read-only, fail-closed MD market recovery shadow audit.

This ONLY audits local MD full-image/delta observations. It is not a ZK
fencing, Order durable HEAD, Gateway publication or MD promotion attestation.
"""
import argparse
import datetime as dt
import json
from pathlib import Path
import re

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

PATTERN = re.compile(
    r"(?P<time>\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) INFO "
    r"MD_RECOVERY_SHADOW_OBSERVATION "
    r"trackedMarkets=(?P<tracked>\d+), contiguous=(?P<fresh>\d+), "
    r"stale=(?P<stale>\d+), gapMarkets=(?P<gap>\d+), "
    r"gapEvents=(?P<events>\d+), promotionAuthorized=false"
)


def evaluate(log_text, expected_markets, now=None, max_age_seconds=180,
             minimum_interval_seconds=15, max_interval_seconds=120):
    if not isinstance(log_text, str) or expected_markets < 1 or expected_markets > 50000:
        raise ValueError("expected market count and log required")
    timezone = ZoneInfo("Asia/Shanghai") if ZoneInfo is not None else dt.timezone(
        dt.timedelta(hours=8))
    now = now or dt.datetime.now(timezone)
    now = now.astimezone(timezone)
    samples = []
    for match in PATTERN.finditer(log_text):
        when = dt.datetime.strptime(match.group("time"), "%Y/%m/%d %H:%M:%S.%f")
        when = when.replace(tzinfo=timezone)
        samples.append({"time": when, **{
            field: int(match.group(field))
            for field in ("tracked", "fresh", "stale", "gap", "events")}})
    # Only the LATEST two samples count. No cherry-picking early successes.
    latest = samples[-2:]
    blockers = []
    if len(latest) < 2:
        blockers.append("TWO_CONSECUTIVE_SHADOW_SAMPLES_REQUIRED")
    else:
        spacing = (latest[1]["time"] - latest[0]["time"]).total_seconds()
        if spacing < minimum_interval_seconds or spacing > max_interval_seconds:
            blockers.append("INVALID_AUDIT_INTERVAL")
        for i, row in enumerate(latest, start=1):
            age = (now - row["time"]).total_seconds()
            if age < 0 or age > max_age_seconds:
                blockers.append("MISSING_FRESH_AUDIT_SAMPLE_%d" % i)
            if row["tracked"] != expected_markets or row["fresh"] != expected_markets:
                blockers.append("INCOMPLETE_MARKET_OBSERVATION_%d" % i)
            # gapEvents is a cumulative diagnostic counter. One recovered
            # historical gap MUST NOT permanently prevent future recovery.
            # Require zero CURRENT gap markets and no NEW gap in the window.
            if row["stale"] or row["gap"]:
                blockers.append("STALE_OR_GAPPED_MARKETS_%d" % i)
        if latest[1]["events"] != latest[0]["events"]:
            blockers.append("GAP_EVENTS_CHANGED_DURING_OBSERVATION")
    return {
        "schema": "md-shadow-local-observation-v1",
        "decision": "PASS_LOCAL_OBSERVATION_ONLY" if not blockers else "BLOCKED",
        "promotionAuthorized": False,
        "canInjectMdPrimaryFault": False,
        "hasSignedOrderDurableHead": False,
        "hasGatewayOldPublisherFence": False,
        "expectedMarkets": expected_markets,
        "samples": [
            {"timestamp": item["time"].isoformat(), "tracked": item["tracked"],
             "fresh": item["fresh"], "stale": item["stale"],
             "gapMarkets": item["gap"], "gapEvents": item["events"]}
            for item in latest],
        "historicalGapEvents": latest[-1]["events"] if latest else None,
        "newGapEventsInWindow": (latest[1]["events"] - latest[0]["events"])
            if len(latest) == 2 else None,
        "blockers": blockers
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--markets", type=int, required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-age-seconds", type=int, default=180)
    args = parser.parse_args()
    if args.max_age_seconds < 30 or args.max_age_seconds > 600:
        parser.error("max age must be 30..600 seconds")
    if not args.log.is_file() or args.log.is_symlink() or args.log.stat().st_size > 2**28:
        parser.error("existing bounded non-symlink log required")
    result = evaluate(args.log.read_text(errors="replace"),
                      args.markets, max_age_seconds=args.max_age_seconds)
    if args.output.exists() or args.output.is_symlink():
        parser.error("output must be a NEW file; never overwrite old evidence")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps(result, indent=2))
    return 0 if result["decision"] == "PASS_LOCAL_OBSERVATION_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
