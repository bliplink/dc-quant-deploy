"""Freeze the unused, distinct-family reserve from an already completed validation screen.

No data is re-screened and no parameter is changed. Families whose symbol/scene
combination already consumed formal results are excluded, including the other side.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from recovery.run_local_historical_scene_campaign import write_json


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign-dir', type=Path, required=True)
    parser.add_argument('--formal-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if not (args.campaign_dir / 'SCREEN_COMPLETE.json').is_file():
        raise ValueError('parent validation campaign is incomplete')
    if not (args.formal_dir / 'FORMAL_COMPLETE.json').is_file():
        raise ValueError('initial formal candidate list has unresolved executions')
    manifest = json.loads((args.campaign_dir / 'campaign.json').read_text(encoding='utf-8'))
    family_by_name = {row['hypothesis']: row['family'] for row in manifest['catalog']}
    consumed = json.loads((args.formal_dir / 'results.json').read_text(encoding='utf-8'))
    consumed_keys = {(row['symbol'], row['scene'], family_by_name[row['hypothesis']]) for row in consumed}
    rows, source_hashes = [], {}
    for path in sorted((args.campaign_dir / 'cells').glob('*/*/validation_results.tsv')):
        source_hashes[str(path.relative_to(args.campaign_dir))] = sha(path)
        with path.open(encoding='utf-8', newline='') as stream:
            rows.extend(row for row in csv.DictReader(stream, delimiter='\t') if row['accepted'] == 'YES')
    rows.sort(key=lambda row: (row['symbol'], row['scene'], -float(row['wf_validate_bps']),
                               -float(row['wf_validate_pf']), row['hypothesis']))
    reserve, seen = [], set(consumed_keys)
    for row in rows:
        family = family_by_name[row['hypothesis']]
        key = (row['symbol'], row['scene'], family)
        if key in seen:
            continue
        if row['wf_forward_bps'] != 'WITHHELD':
            raise ValueError('reserve contains exposed screen forward metrics')
        seen.add(key)
        reserve.append({**row, 'family': family, 'requires_semantic_review': True, 'qualified': False})
    reserve_manifest = {**manifest, 'version': 'fixed_representative_reserve_v1',
                        'parent_campaign_sha256': sha(args.campaign_dir / 'campaign.json'),
                        'consumed_results_sha256': sha(args.formal_dir / 'results.json'),
                        'source_validation_sha256': source_hashes,
                        'shortlist_rule': 'remaining fixed validation ranking; exclude all consumed symbol-scene-families',
                        'prior_formal_results_consumed': len(consumed)}
    if (args.output_dir / 'campaign.json').exists():
        existing = json.loads((args.output_dir / 'campaign.json').read_text(encoding='utf-8'))
        if existing != reserve_manifest:
            raise ValueError('reserve source evidence changed; use a new directory')
        if json.loads((args.output_dir / 'shortlist.json').read_text(encoding='utf-8')) != reserve:
            raise ValueError('frozen reserve ordering changed')
    else:
        write_json(args.output_dir / 'campaign.json', reserve_manifest)
        write_json(args.output_dir / 'shortlist.json', reserve)
        write_json(args.output_dir / 'SCREEN_COMPLETE.json', {
            'parent_screen_complete_sha256': sha(args.campaign_dir / 'SCREEN_COMPLETE.json'),
            'screen_holdout_withheld': True, 'prior_formal_results_consumed': len(consumed),
            'shortlisted': len(reserve), 'production_write': False})
    print('frozen unused family candidates', len(reserve), 'already consumed families', len(consumed_keys))


if __name__ == '__main__':
    main()
