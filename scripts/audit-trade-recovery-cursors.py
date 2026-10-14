#!/usr/bin/env python3
"""Read-only, bounded audit of Trade snapshot/journal mismatch evidence.

It never opens Chronicle Queue for writing and never deletes staged recovery data.
A log-reported localLastSeq is an observation, NOT a durable current watermark.
"""
import argparse
import json
import re
from pathlib import Path

GAP = re.compile(
    r"TradeSvr snapshot is ahead of local journal partition=(P[0-9]{3}), "
    r"snapshotSeq=([0-9]+), localLastSeq=([0-9]+)"
)
META = {k: re.compile(rb'"' + k.encode('ascii') + rb'"\s*:\s*([0-9]+)')
        for k in ('snapshotSeq', 'committedStateSeq', 'committedStateEpoch', 'epoch')}
SENSITIVE = ('balances', 'positions', 'accounts', 'orders')


def parse_metadata(path):
    if not path.is_file() or path.is_symlink():
        return None
    with path.open('rb') as stream:
        header = stream.read(4096)
    result = {}
    for key, rx in META.items():
        match = rx.search(header)
        if match is None:
            return {'invalidHeader': True}
        result[key] = int(match.group(1))
    return result


def parse_baseline(path):
    if not path.is_file() or path.is_symlink():
        return None
    result = {}
    for line in path.read_text(errors='replace').splitlines():
        if line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        if key in ('baselineSeq', 'commitMarkerSeq', 'committedStateSeq', 'epoch'):
            try:
                result[key] = int(value)
            except ValueError:
                return {'invalidBaseline': True}
    return result


def recent_log_observations(path, max_bytes=4 * 1024 * 1024):
    if not path.is_file() or path.is_symlink():
        return {}
    # Avoid scanning large active logs or recording account data.
    with path.open('rb') as stream:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(max(0, size - max_bytes))
        chunk = stream.read(max_bytes).decode('utf-8', errors='replace')
    observations = {}
    for name, snapshot, journal in GAP.findall(chunk):
        observations[name] = (int(snapshot), int(journal))
    return observations


def audit(data_root, log_root, nodes):
    result = {'scope': 'READ_ONLY_NO_AUTO_RECOVERY', 'nodes': {}, 'unresolvedCount': 0}
    for node in nodes:
        if node not in ('TradeSvrA', 'TradeSvrB'):
            raise ValueError('only known Trade nodes may be inspected')
        observations = recent_log_observations(log_root / (node + '.log'))
        rows = []
        for part, (observed_snapshot, last_seq) in sorted(observations.items()):
            metadata = parse_metadata(data_root / node / 'snapshot' / part / 'latest.json')
            baseline = parse_baseline(data_root / node / 'journal' / part / 'baseline.properties')
            actual = metadata.get('snapshotSeq') if metadata else None
            # Local WAL tail comes from recent error logs, not a fresh Chronicle
            # read. Never claim a current cursor or invent a source-proof.
            unresolved = actual is None or actual > last_seq
            row = {'partition': part, 'logSnapshotSeq': observed_snapshot,
                   'logObservedLocalLastSeq': last_seq,
                   'currentSnapshotMetadata': metadata, 'journalBaseline': baseline,
                   'requiresAuthoritativeRecoveryProof': unresolved}
            rows.append(row)
            result['unresolvedCount'] += int(unresolved)
        result['nodes'][node] = {'observedProblemPartitions': len(rows),
                                 'details': rows}
    result['decision'] = 'BLOCKED' if result['unresolvedCount'] else 'NO_GAP_IN_LOG_TAIL_NOT_A_PROOF'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True, type=Path)
    parser.add_argument('--log-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output already exists; do not overwrite audit evidence')
    result = audit(args.data_root, args.log_root, ('TradeSvrA', 'TradeSvrB'))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'decision': result['decision'],
                      'unresolvedCount': result['unresolvedCount'],
                      'byNode': {k: v['observedProblemPartitions']
                                 for k, v in result['nodes'].items()}}))
    return 2 if result['unresolvedCount'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
