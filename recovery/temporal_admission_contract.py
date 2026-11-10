"""Temporal isolation is an extra source-release gate, not a substitute for financial gates."""

import json
from datetime import date, timedelta


def temporal_overlap_evidence(result, holdout_begin, holdout_end):
    first, last = date.fromisoformat(holdout_begin), date.fromisoformat(holdout_end)
    overlaps = []
    for row in result.get('sliceResults') or []:
        for phase in ('fit', 'validate', 'forward'):
            begin, end = date.fromisoformat(row[phase + 'Begin']), date.fromisoformat(row[phase + 'End'])
            if begin <= last and end >= first:
                overlaps.append({'slice': row['sliceNo'], 'phase': phase,
                    'begin': str(max(begin, first)), 'end': str(min(end, last))})
    return {'holdout_begin': holdout_begin, 'holdout_end': holdout_end,
            'overlaps': overlaps, 'fully_disjoint': not overlaps,
            'holdout_parameter_policy': (result.get('holdout') or {}).get('parameterPolicy'),
            'financial_observations_unchanged': True}


def require_temporally_isolated_admission(envelope, require_risk_profile=True):
    result = envelope.get('result') or {}
    holdout = result.get('holdout') or {}
    if result.get('admissionSchema') != 'local_temporal_holdout_v2':
        raise ValueError('fit-risk admission requires the explicit temporal v2 contract')
    primary_end = date.fromisoformat(result['endDate'])
    first, last = date.fromisoformat(holdout['beginDate']), date.fromisoformat(holdout['endDate'])
    if first != primary_end + timedelta(days=1) or (last - first).days + 1 < 62:
        raise ValueError('holdout must immediately follow the primary period and retain at least 62 days')
    rows = result.get('sliceResults') or []
    if len(rows) < 3:
        raise ValueError('at least three complete primary slices are required')
    primary_begin = date.fromisoformat(result['beginDate'])
    previous_forward_end = None
    for index, row in enumerate(rows):
        boundaries = [date.fromisoformat(row[phase + edge])
                      for phase in ('fit', 'validate', 'forward') for edge in ('Begin', 'End')]
        if boundaries != sorted(boundaries) or boundaries[0] < primary_begin or boundaries[-1] > primary_end:
            raise ValueError('primary slice crosses the primary/holdout boundary or is out of order')
        if (row['sliceNo'] != index + 1 or boundaries[1] + timedelta(days=1) != boundaries[2]
                or boundaries[3] + timedelta(days=1) != boundaries[4]
                or (previous_forward_end is not None and boundaries[2] <= previous_forward_end)):
            raise ValueError('primary phases must be adjacent and validation/forward slices non-overlapping')
        previous_forward_end = boundaries[5]
    if not temporal_overlap_evidence(result, str(first), str(last))['fully_disjoint']:
        raise ValueError('primary windows overlap chronological holdout')
    selected = result.get('selectedParameters')
    if not isinstance(selected, dict):
        raise ValueError('primary selected parameters must be explicit, even for fixed sources')
    if require_risk_profile and (set(selected) != {'riskProfile'}
            or type(selected['riskProfile']) is not int or selected['riskProfile'] not in (0, 1, 2, 3)):
        raise ValueError('risk profile must be explicitly selected before holdout')
    representative = result.get('bestParamSetJson')
    if isinstance(representative, str):
        representative = json.loads(representative)
    if (representative != selected or holdout.get('lockedParameters') != selected
            or holdout.get('parameterPolicy') != 'frozen_pre_holdout_representative'):
        raise ValueError('holdout does not lock the exact primary representative parameters')
    if holdout.get('optimizerInvocations') != 0 or holdout.get('fitInvocations') != 0:
        raise ValueError('holdout must not perform fitting or optimization')
    if (not envelope.get('sourceSha256') or holdout.get('sourceSha256') != envelope['sourceSha256']
            or envelope.get('productionWrite') is not False):
        raise ValueError('holdout must use the same frozen source without production writes')
    return {'temporal_isolation': True, 'locked_parameters': selected,
            'holdout_calendar_days': (last - first).days + 1}


def main():
    import argparse
    import hashlib
    from pathlib import Path
    from recovery.strategy_recovery_common import atomic_write_json
    parser = argparse.ArgumentParser(description='Read-only audit of an existing admission envelope temporal boundaries')
    parser.add_argument('--legacy-envelope', type=Path, required=True)
    parser.add_argument('--output-file', type=Path, required=True)
    parser.add_argument('--holdout-begin', required=True)
    parser.add_argument('--holdout-end', required=True)
    args = parser.parse_args()
    if args.output_file.exists():
        raise ValueError('preserve earlier audit evidence; output must be new')
    data = args.legacy_envelope.read_bytes()
    envelope = json.loads(data)
    result = envelope['result']
    audit = temporal_overlap_evidence(result, args.holdout_begin, args.holdout_end)
    audit.update({'schema': 'legacy_temporal_boundary_audit_v1',
        'source_envelope_sha256': hashlib.sha256(data).hexdigest(),
        'primary_begin': result['beginDate'], 'primary_end': result['endDate'],
        'primary_had_parameter_dimensions': any(json.loads(row.get('paramSetJson') or '{}')
                                              for row in result.get('optimizationTrials') or []),
        'original_financial_qualified': result['qualified'],
        'production_write': False, 'old_financial_observations_still_consumed': True})
    atomic_write_json(args.output_file, audit)
    print('LEGACY_TEMPORAL_BOUNDARY_AUDIT overlaps', len(audit['overlaps']),
          'fit_has_parameters', audit['primary_had_parameter_dimensions'])


if __name__ == '__main__':
    main()
