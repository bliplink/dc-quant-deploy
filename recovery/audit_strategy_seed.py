"""Audit archived live-strategy source for deterministic integrity defects.

This is a local, read-only source audit. An archived seed may not match the
currently ACTIVE version; those entries are reported as stale, not repaired.
"""

import argparse
import base64
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


PARAMETER_CALL = re.compile(r'\bparam(?:Int|Double|Boolean)\s*\(\s*"([^"]+)"')
SOURCE_INTEGRITY_FLAGS = frozenset({
    'source_sha256_mismatch', 'stop_price_missing', 'take_price_missing',
    'signal_side_missing',
})


def audit(seed, active_rows):
    active = {}
    for row in active_rows:
        active.setdefault(row['strategy_name'], []).append(row)
    findings = []
    for item in seed['strategies']:
        name = item['strategyName']
        request = item['request']
        raw = base64.b64decode(request['javaSourceBase64'], validate=True)
        source = raw.decode('utf-8')
        used = set(PARAMETER_CALL.findall(source))
        declared = set(request['defaultParameters'])
        matching_rows = active.get(name, [])
        current = next((row for row in matching_rows
                        if row['strategy_version'] == item['sourceStrategyVersion']),
                       matching_rows[0] if matching_rows else None)
        flags = []
        if hashlib.sha256(raw).hexdigest() != item['sourceSha256']:
            flags.append('source_sha256_mismatch')
        if used - declared:
            flags.append('parameter_defaults_missing')
        if declared - used:
            flags.append('unused_default_parameters')
        if 'signal.stopPrice' not in source:
            flags.append('stop_price_missing')
        if 'signal.takerPrice' not in source:
            flags.append('take_price_missing')
        if 'signal.side' not in source:
            flags.append('signal_side_missing')
        if current is None:
            flags.append('not_currently_active')
        elif current['strategy_version'] != item['sourceStrategyVersion']:
            flags.append('archived_version_stale')
        findings.append({
            'strategy_name': name,
            'seed_version': item['sourceStrategyVersion'],
            'active_version': current['strategy_version'] if current else None,
            'symbol': item['symbol'],
            'scene': item['scene'],
            'qualification': current['reason'] if current else None,
            'flags': flags,
            'missing_defaults': sorted(used - declared),
            'unused_defaults': sorted(declared - used),
            'source_sha256': item['sourceSha256'],
        })
    return findings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', required=True)
    parser.add_argument('--active-snapshot', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    seed = json.loads(Path(args.seed).read_text(encoding='utf-8'))
    with Path(args.active_snapshot).open(encoding='utf-8', newline='') as stream:
        active_rows = list(csv.DictReader(stream, delimiter='\t'))
    findings = audit(seed, active_rows)
    flags = Counter(flag for item in findings for flag in item['flags'])
    summary = {'seed_count': len(findings), 'active_snapshot_count': len(active_rows),
               'source_integrity_issue_count': sum(
                   bool(SOURCE_INTEGRITY_FLAGS.intersection(item['flags']))
                   for item in findings if item['active_version'] == item['seed_version']),
               'flag_counts': dict(flags), 'findings': findings}
    Path(args.output).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'seed_count': len(findings), 'active_snapshot_count': len(active_rows),
                      'source_integrity_issue_count': summary['source_integrity_issue_count'],
                      'flag_counts': dict(flags)}, indent=2))


if __name__ == '__main__':
    main()
