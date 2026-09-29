#!/usr/bin/env python3
"""Compose immutable full-release evidence from a verified base and scoped rebuild."""

import argparse
import json
from pathlib import Path


def merge(lock, base, delta):
    expected = {item['name']: item for item in lock['components']}
    if set(base['components']) != set(expected):
        raise ValueError('base evidence must cover every locked component')
    if not delta['components'] or set(delta['components']) - set(expected):
        raise ValueError('delta evidence must contain known rebuilt components')
    combined = {}
    for name, item in expected.items():
        result = (delta['components'] if name in delta['components'] else base['components'])[name]
        if result['revision'] != item['revision']:
            raise ValueError(f'{name}: evidence source revision differs from lock')
        tests = result.get('tests', {})
        if tests.get('failures', 0) or tests.get('errors', 0):
            raise ValueError(f'{name}: tests failed')
        if item['type'] != 'library' and not result.get('imageId'):
            raise ValueError(f'{name}: missing built image id')
        combined[name] = result
    return {
        'releaseId': lock['releaseId'],
        'baseReleaseId': base['releaseId'],
        'deltaReleaseId': delta['releaseId'],
        'mavenImage': delta.get('mavenImage', base.get('mavenImage')),
        'jreImage': delta.get('jreImage', base.get('jreImage')),
        'components': combined,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--base-evidence', type=Path, required=True)
    parser.add_argument('--delta-evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('output evidence already exists')
    payload = merge(*(json.loads(path.read_text()) for path in
                      (args.lock, args.base_evidence, args.delta_evidence)))
    args.output.write_text(json.dumps(payload, indent=2) + '\n')
    print(f"LOCKED_RELEASE_EVIDENCE_PASS components={len(payload['components'])} "
          f"rebuilds={len(json.loads(args.delta_evidence.read_text())['components'])}")


if __name__ == '__main__':
    main()
