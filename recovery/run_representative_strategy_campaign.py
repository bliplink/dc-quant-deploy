"""Checkpointed local validation of one fixed parameter set per signal implementation.

The chronological holdout stays withheld. Shortlists are research candidates only;
qualification, semantic duplicate review and server publication are later stages.
"""

import argparse
import csv
import hashlib
import io
import json
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from recovery.run_local_strategy_validation import SYMBOLS, assert_research_protocol
from recovery.run_local_historical_scene_campaign import write_json


SCENES = ('trend', 'range', 'channel', 'breakout', 'reversal')
CATALOG_CLASS = 'com.app.dc.service.strategy.research.StrategyRepresentativeCatalogCli'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_rows(path):
    with path.open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream, delimiter='\t'))


def select_shortlist(rows, catalog, missing):
    families = {row['hypothesis']: row['family'] for row in catalog}
    grouped = {}
    for row in rows:
        if row['accepted'] != 'YES':
            continue
        cell = row['symbol'] + '/' + row['scene']
        grouped.setdefault(cell, []).append({**row, 'family': families[row['hypothesis']]})
    result = []
    for cell, candidates in sorted(grouped.items()):
        candidates.sort(key=lambda row: (-float(row['wf_validate_bps']),
                                        -float(row['wf_validate_pf']), row['hypothesis']))
        selected_families = set()
        for row in candidates:
            if len(selected_families) >= missing.get(cell, 0):
                break
            if row['family'] in selected_families:
                continue
            selected_families.add(row['family'])
            result.append({**row, 'requires_semantic_review': True, 'qualified': False})
    return result


def run_task(args, symbol, scene, catalog_names, manifest_sha):
    output = args.output_dir / 'cells' / symbol / scene
    checkpoint = output / 'checkpoint.json'
    if checkpoint.is_file():
        saved = json.loads(checkpoint.read_text(encoding='utf-8'))
        if (saved['manifest_sha256'] != manifest_sha
                or saved['results_sha256'] != sha(output / 'validation_results.tsv')):
            raise ValueError('changed campaign checkpoint: ' + str(output))
        return read_rows(output / 'validation_results.tsv'), True
    output.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-u', '-m', 'recovery.run_local_strategy_validation',
               '--java', args.java, '--classes', args.classes,
               '--input-dir', str(args.input_dir), '--output-dir', str(output),
               '--scene', scene, '--symbols', symbol, '--cohort', args.cohort, '--pattern', '.*',
               '--begin', '2024-12-15', '--end', '2025-08-11',
               '--protocol', str(args.protocol), '--representative-catalog',
               '--java-heap-mb', str(args.java_heap_mb)]
    with (output / 'runner.log').open('w', encoding='utf-8') as stream:
        completed = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                                   timeout=args.timeout_minutes * 60)
    if completed.returncode:
        raise RuntimeError('screen failed; inspect ' + str(output / 'runner.log'))
    rows = read_rows(output / 'validation_results.tsv')
    if (len(rows) != len(catalog_names)
            or {row['hypothesis'] for row in rows} != catalog_names
            or any(row['symbol'] != symbol or row['scene'] != scene
                   or row['wf_forward_bps'] != 'WITHHELD' for row in rows)):
        raise ValueError('screen results differ from frozen catalog: ' + str(output))
    write_json(checkpoint, {'manifest_sha256': manifest_sha,
                            'results_sha256': sha(output / 'validation_results.tsv')})
    return rows, False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--classes', required=True)
    parser.add_argument('--indsvr-repo', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--java', default='java')
    parser.add_argument('--cohort', default='all', choices=('all', 'structural_v1', 'statistical_v1', 'frozen_supervised_v1', 'execution_path_v1', 'regime_consensus_v1', 'structural_meta_v1', 'structural_expectancy_v1', 'volatility_exit_v1', 'formal_payoff_v1', 'catalog_atr_exit_v1'),
                        help='Explicit frozen research cohort; all preserves prior campaigns')
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--java-heap-mb', type=int, default=384)
    parser.add_argument('--timeout-minutes', type=int, default=60)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.workers <= 2 or not 128 <= args.java_heap_mb <= 1024:
        parser.error('workers must be 1..2 and heap must be 128..1024 MiB')
    args.input_dir = args.input_dir.resolve()
    args.output_dir = args.output_dir.resolve()
    args.protocol = args.protocol.resolve()
    assert_research_protocol(args.protocol, args.input_dir,
                             '2024-12-15', '2025-08-11', SYMBOLS)
    catalog_process = subprocess.run(
        [args.java, '-Ddc.research.listRepresentativesOnly=true', '-Ddc.research.cohort=' + args.cohort, '-cp', args.classes,
         CATALOG_CLASS], capture_output=True, text=True, encoding='utf-8', check=True)
    catalog = list(csv.DictReader(io.StringIO(catalog_process.stdout), delimiter='\t'))
    names = {row['hypothesis'] for row in catalog}
    if (not catalog or len(names) != len(catalog)
            or len({(row['family'], row['direction']) for row in catalog}) != len(catalog)):
        raise ValueError('duplicate or empty representative catalog')
    baseline = read_rows(args.snapshot)
    occupied = Counter(row['symbol_scope'] + '/' + row['scene'] for row in baseline
                       if row['reason'] == 'qualified')
    missing = {symbol + '/' + scene: max(0, 2 - occupied[symbol + '/' + scene])
               for symbol in SYMBOLS for scene in SCENES}
    source_dir = args.indsvr_repo / 'src/test/java/com/app/dc/service/strategy/research'
    class_dir = args.indsvr_repo / 'target/test-classes/com/app/dc/service/strategy/research'
    manifest = {'version': 'fixed_representative_catalog_v1', 'production_write': False,
                'screen_begin': '2024-12-15', 'screen_end_inclusive': '2025-08-11',
                'holdout_begin': '2025-08-12', 'holdout_end_inclusive': '2025-10-12',
                'ready_sha256': sha(args.input_dir / 'READY.json'),
                'protocol_sha256': sha(args.protocol), 'snapshot_sha256': sha(args.snapshot),
                'catalog': catalog, 'missing_slots': missing,
                'shortlist_rule': 'validate_net_bps_desc_pf_desc; one per signal class per cell',
                'source_sha256': {name: sha(source_dir / (name + '.java')) for name in
                                  ('StrategyResearchBatchCli', 'StrategyRepresentativeCatalogCli')},
                'class_sha256': {path.name: sha(path) for path in sorted(class_dir.glob('*.class'))}}
    if args.cohort != 'all':
        manifest['cohort'] = args.cohort
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / 'campaign.json'
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding='utf-8')) != manifest:
            raise ValueError('campaign inputs changed; use a new output directory')
    else:
        write_json(manifest_path, manifest)
        (args.output_dir / 'catalog.tsv').write_text(catalog_process.stdout, encoding='utf-8')
    print('catalog', len(catalog), 'families', len({row['family'] for row in catalog}),
          'missing slots', sum(missing.values()), 'planned screens', len(catalog) * 50, flush=True)
    if args.prepare_only:
        return
    manifest_sha = sha(manifest_path)
    all_rows = []
    errors = []
    completed_cells = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        tasks = {executor.submit(run_task, args, symbol, scene, names, manifest_sha): (symbol, scene)
                 for symbol in SYMBOLS for scene in SCENES}
        for future in as_completed(tasks):
            symbol, scene = tasks[future]
            try:
                rows, resumed = future.result()
                all_rows.extend(rows)
                completed_cells += 1
                print(symbol, scene, 'tested', len(rows), 'pass',
                      sum(row['accepted'] == 'YES' for row in rows),
                      'resumed' if resumed else 'new', flush=True)
            except Exception as error:
                errors.append({'symbol': symbol, 'scene': scene, 'error': str(error)})
                print('ERROR', symbol, scene, str(error), flush=True)
            shortlist = select_shortlist(all_rows, catalog, missing)
            write_json(args.output_dir / 'status.json', {
                'updated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'completed_cells': completed_cells, 'total_cells': 50,
                'tested': len(all_rows), 'validation_pass': sum(row['accepted'] == 'YES' for row in all_rows),
                'shortlisted': len(shortlist), 'formal_qualified': 0, 'published': 0,
                'errors': errors})
            write_json(args.output_dir / 'shortlist.json', shortlist)
    if errors:
        raise RuntimeError('campaign contains failed screens; inspect status.json')
    write_json(args.output_dir / 'SCREEN_COMPLETE.json', {
        'manifest_sha256': manifest_sha, 'tested': len(all_rows), 'shortlisted': len(shortlist),
        'holdout_withheld': True, 'production_write': False})


if __name__ == '__main__':
    main()
