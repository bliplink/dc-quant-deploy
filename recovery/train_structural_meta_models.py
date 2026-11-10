"""Train frozen event-conditional acceptance models, never server-generated code.

The old structural rule defines an entry event. A new year-balanced conditional
profit model can reject it; it cannot create entries the original rule did not emit.
"""

import argparse
import csv
import hashlib
import json
import os
import subprocess
from pathlib import Path

from recovery.export_representative_candidate import declaration
from recovery.strategy_recovery_common import atomic_write_json
from recovery.train_execution_path_models import execution_features, path_label, HORIZON
from recovery.train_frozen_strategy_models import load_training_prefix, restored_prediction


FAMILIES = (
    'AuctionValueRejectionHypothesis', 'OpeningBalanceAcceptanceHypothesis',
    'MultiAuctionBalanceEscapeHypothesis', 'FailedSessionAcceptanceHypothesis',
    'BipowerJumpContinuationHypothesis', 'SemivarianceRecoveryHypothesis',
    'ValueOccupationMigrationHypothesis', 'DisplacementGapDefenseHypothesis',
    'DisplacementOriginDefenseHypothesis', 'ContinuousVarianceReleaseHypothesis',
)


def balanced_year_weights(years):
    import numpy as np
    years = np.asarray(years)
    if set(years.tolist()) != {2022, 2023, 2024}:
        raise ValueError('every training model requires all three historical years')
    return np.asarray([len(years) / (3 * np.sum(years == year)) for year in years])


def event_samples(frame, event_rows):
    import numpy as np
    import pandas as pd
    x, volatility = execution_features(frame)
    prices = frame[['open', 'high', 'low', 'close']].to_numpy(dtype=float)
    selected, last, seen = {}, {}, {}
    for row in event_rows:
        family, side, i = row['family'], int(row['side']), int(row['index'])
        if family not in FAMILIES or side not in (-1, 1) or not 199 <= i < len(frame):
            raise ValueError('invalid structural event identity')
        if int(frame.iloc[i]['time'].timestamp() * 1000) != int(row['time']):
            raise ValueError('event timestamp differs from frozen bars')
        key = (family, side)
        if i <= seen.get(key, -1000):
            raise ValueError('events are duplicated or unordered within a rule/direction')
        seen[key] = i
        # Fixed chronological thinning, unrelated to any financial result.
        if i - last.get(key, -1000) < 16:
            continue
        last[key] = i
        if i + HORIZON >= len(frame):
            continue
        if frame.iloc[i + HORIZON]['time'] >= pd.Timestamp('2024-12-15', tz='UTC'):
            continue
        if (frame.iloc[i + HORIZON]['time'] - frame.iloc[i - 199]['time']
                != pd.Timedelta(minutes=(HORIZON + 199) * 15)):
            continue
        if not np.isfinite(x[i]).all():
            continue
        label = path_label(prices, i, volatility[i] * prices[i, 3], side)
        if label is None:
            continue
        net, end, reason = label
        year = frame.iloc[i]['time'].year
        if frame.iloc[end]['time'].year != year:
            continue
        selected.setdefault(key, []).append((x[i], net / volatility[i], year, i, end))
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--event-repo', type=Path, required=True)
    parser.add_argument('--rule-repo', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if (output / 'TRAINING_COMPLETE.json').exists():
        raise ValueError('models already frozen; cannot retrain an inspected hypothesis')
    import numpy as np
    import sklearn
    from sklearn.ensemble import GradientBoostingRegressor
    from threadpoolctl import threadpool_limits
    ready = json.loads((args.input_dir / 'READY.json').read_text(encoding='utf-8'))
    if ready.get('purpose') != 'training_only' or ready.get('train_end_exclusive') != '2024-12-15':
        raise ValueError('unchanged pre-validation training input required')
    source_path = args.rule_repo / 'src/test/java/com/app/dc/service/strategy/research/StrategyResearchBatchCli.java'
    source = source_path.read_text(encoding='utf-8')
    rules_sha = hashlib.sha256('\n'.join(declaration(source, name) for name in FAMILIES).encode('utf-8')).hexdigest()
    core_class = args.rule_repo / 'target/test-classes/com/app/dc/service/strategy/research/StrategyResearchBatchCli.class'
    event_class = args.event_repo / 'target/test-classes/com/app/dc/service/strategy/research/StructuralTrainingEventsCli.class'
    classpath = os.pathsep.join([str(args.event_repo / 'target/test-classes'), str(args.rule_repo / 'target/test-classes')])
    output.mkdir(parents=True, exist_ok=True)
    pools, evidence, probes = {}, [], []
    for symbol, file in sorted(ready['files'].items()):
        path = args.input_dir / (symbol + '-15m.tsv')
        if hashlib.sha256(path.read_bytes()).hexdigest() != file['bars_sha256']:
            raise ValueError('changed training history')
        folder = output / 'events' / symbol
        folder.mkdir(parents=True, exist_ok=True)
        event_path = folder / 'events.tsv'
        checkpoint = folder / 'checkpoint.json'
        frozen = {'bars_sha256': file['bars_sha256'], 'base_rules_sha256': rules_sha,
            'core_class_sha256': hashlib.sha256(core_class.read_bytes()).hexdigest(),
            'event_cli_sha256': hashlib.sha256(event_class.read_bytes()).hexdigest()}
        if checkpoint.exists():
            saved = json.loads(checkpoint.read_text(encoding='utf-8'))
            if saved['frozen'] != frozen or saved['events_sha256'] != hashlib.sha256(event_path.read_bytes()).hexdigest():
                raise ValueError('changed event checkpoint')
        else:
            with event_path.open('w', encoding='utf-8') as stream, (folder / 'events.stderr.log').open('w', encoding='utf-8') as error:
                result = subprocess.run(['java', '-Xmx384m', '-cp', classpath,
                    'com.app.dc.service.strategy.research.StructuralTrainingEventsCli', str(path)],
                    stdout=stream, stderr=error, timeout=900)
            if result.returncode:
                raise ValueError('causal event export failed: ' + symbol)
            atomic_write_json(checkpoint, {'frozen': frozen,
                'events_sha256': hashlib.sha256(event_path.read_bytes()).hexdigest()})
        frame = load_training_prefix(path)
        with event_path.open(encoding='utf-8') as stream:
            selected = event_samples(frame, csv.DictReader(stream, delimiter='\t'))
        for key, rows in selected.items():
            pools.setdefault(key, []).extend(rows)
            evidence.append({'symbol': symbol, 'family': key[0], 'side': key[1], 'labels': len(rows),
                'last_label_time': str(frame.iloc[max(row[4] for row in rows)]['time'])})
            if not probes:
                probes = [row[0].tolist() for row in rows[:8]]
        atomic_write_json(output / 'training-status.json', {'completed_symbols': len({r['symbol'] for r in evidence}),
            'current_symbol': symbol, 'training_only': True, 'server_or_llm_calls': 0})
        print('STRUCTURAL_EVENTS', symbol, sum(len(rows) for rows in selected.values()), flush=True)
    manifest = {'version': 'structural_meta_v1', 'families': list(FAMILIES), 'features': 18,
        'base_rules_sha256': rules_sha, 'input': evidence, 'training_cutoff_exclusive': '2024-12-15',
        'year_balancing': 'equal aggregate weight for each of 2022,2023,2024',
        'thinning_bars_per_family_direction': 16, 'potential_label_horizon': HORIZON,
        'overlapping_training_labels': True, 'independence_or_significance_claim': False,
        'server_or_llm_calls': 0, 'financial_holdout_evaluated': False,
        'sklearn_version': sklearn.__version__, 'trainer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'label_helper_sha256': hashlib.sha256(Path(__file__).with_name('train_execution_path_models.py').read_bytes()).hexdigest(),
        'ready_sha256': hashlib.sha256((args.input_dir / 'READY.json').read_bytes()).hexdigest(),
        'parameters': {'trees': 24, 'max_depth': 2, 'min_leaf': 50, 'learning_rate': .05,
                       'seed': 20261110, 'minimum_labels': 200, 'minimum_labels_each_year': 20},
        'acceptance_rule': 'original structural entry event AND predicted net return > 8bps',
        'opposite_model_comparison': False,
        'reason_no_opposite_comparison': 'directional models condition on different structural events, not the same population',
        'proxy_limitations': ['96-bar censor', 'no scene exits', 'no subsequent signal interference',
                              'training cost notional approximation']}
    atomic_write_json(output / 'training-manifest.json', manifest)
    models, skipped = [], []
    with threadpool_limits(limits=1):
        for family in FAMILIES:
            eligible = True
            for side in (1, -1):
                rows = pools.get((family, side), [])
                counts = {year: sum(row[2] == year for row in rows) for year in (2022, 2023, 2024)}
                if len(rows) < 200 or min(counts.values()) < 20:
                    skipped.append({'family': family, 'side': side, 'rows': len(rows), 'year_counts': counts,
                                    'reason': 'insufficient historical event labels'})
                    eligible = False
            if not eligible:
                continue  # Explicitly unavailable, never fall back to the old unfiltered strategy.
            for side in (1, -1):
                rows = pools[family, side]
                x, y = np.vstack([r[0] for r in rows]), np.asarray([r[1] for r in rows])
                weights = balanced_year_weights([r[2] for r in rows])
                fit = GradientBoostingRegressor(loss='huber', n_estimators=24, learning_rate=.05,
                    max_depth=2, min_samples_leaf=50, random_state=20261110).fit(x, y, sample_weight=weights)
                trees = []
                for item in fit.estimators_.ravel():
                    tree = item.tree_
                    trees.append([[int(tree.feature[n]), float(tree.threshold[n]), int(tree.children_left[n]),
                        int(tree.children_right[n]), float(tree.value[n, 0, 0])] for n in range(tree.node_count)])
                model = {'algorithm': 'boosted_tree', 'family': family, 'side': side, 'trees': trees,
                    'initial': float(fit.init_.predict(x[:1])[0]), 'learning_rate': .05, 'rows': len(y)}
                error = float(np.max(np.abs(fit.predict(x[:64]) - restored_prediction(model, x[:64]))))
                if error > 1e-9:
                    raise ValueError('standalone model differs from trained event model')
                model['export_max_abs_error'] = error
                models.append(model)
                print('FROZEN_STRUCTURAL_META', family, side, len(y), error, flush=True)
    package = {'manifest': manifest, 'models': models, 'skipped': skipped, 'probes': [
        {'features': row, 'predictions': [float(restored_prediction(m, np.asarray(row)[None, :])[0])
                                        for m in models]} for row in probes]}
    atomic_write_json(output / 'frozen-models.json', package)
    atomic_write_json(output / 'TRAINING_COMPLETE.json', {'models': len(models), 'strategy_classes': len(models) // 2,
        'skipped': skipped, 'financial_holdout_evaluated': False, 'server_or_llm_calls': 0,
        'frozen_models_sha256': hashlib.sha256((output / 'frozen-models.json').read_bytes()).hexdigest()})


if __name__ == '__main__':
    main()
