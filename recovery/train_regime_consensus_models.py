"""Freeze separate 2022/2023/2024 models; infer using their untuned median.

This is a new cross-regime-consensus hypothesis, not a refit of a failed version.
All labels end before validation; financial READY inputs remain unchanged.
"""

import argparse
import hashlib
import json
from pathlib import Path

from recovery.strategy_recovery_common import atomic_write_json
from recovery.train_execution_path_models import GROUPS, HORIZON, STRIDE, training_samples
from recovery.train_frozen_strategy_models import load_training_prefix, restored_prediction, TRAIN_END_EXCLUSIVE


YEARS = (2022, 2023, 2024)


def median_prediction(models, features, group, algorithm, side):
    import numpy as np
    chosen = [item for item in models if item['group'] == group and item['algorithm'] == algorithm
              and item['side'] == side]
    if len(chosen) != 3 or {item['year'] for item in chosen} != set(YEARS):
        raise ValueError('all three frozen regime models are required')
    return np.median(np.column_stack([restored_prediction(item, features) for item in chosen]), axis=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if (output / 'TRAINING_COMPLETE.json').exists():
        raise ValueError('already frozen; never overwrite an inspected hypothesis')
    import numpy as np
    import sklearn
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    from threadpoolctl import threadpool_limits
    ready = json.loads((args.input_dir / 'READY.json').read_text(encoding='utf-8'))
    if ready.get('purpose') != 'training_only' or ready.get('train_end_exclusive') != TRAIN_END_EXCLUSIVE:
        raise ValueError('explicit training-only input contract required')
    buckets = {(year, side): ([], []) for year in YEARS for side in (1, -1)}
    evidence, probes = [], []
    output.mkdir(parents=True, exist_ok=True)
    for symbol, files in sorted(ready['files'].items()):
        path = args.input_dir / (symbol + '-15m.tsv')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != files['bars_sha256']:
            raise ValueError('training input hash changed')
        frame = load_training_prefix(path)
        for side in (1, -1):
            x, y, observed = training_samples(frame, side, train_begin='2022-01-01', strict_grid=True)
            signal_year = frame.iloc[[row[0] for row in observed]]['time'].dt.year.to_numpy()
            for year in YEARS:
                # A regime's labels must also finish inside that same year.
                same_label_year = np.array([frame.iloc[row[1]]['time'].year == year for row in observed])
                keep = (signal_year == year) & same_label_year
                if keep.sum() < 100:
                    raise ValueError('insufficient observed regime labels: ' + symbol + '/' + str(year))
                buckets[year, side][0].append(x[keep]); buckets[year, side][1].append(y[keep])
                indices = np.flatnonzero(keep)
                evidence.append({'symbol': symbol, 'year': year, 'side': side, 'rows': int(keep.sum()),
                    'bars_sha256': digest,
                    'last_label_time': str(frame.iloc[max(observed[i][1] for i in indices)]['time'])})
            if not probes:
                probes = x[:12].tolist()
        print('REGIME_SAMPLES', symbol, flush=True)
    manifest = {'version': 'regime_consensus_v1', 'years': list(YEARS), 'train_begin': '2022-01-01',
        'train_end_exclusive': TRAIN_END_EXCLUSIVE, 'groups': GROUPS, 'input': evidence,
        'horizon_bars': HORIZON, 'stride_bars': STRIDE, 'overlapping_training_labels': True,
        'independence_or_significance_claim': False, 'features': 18, 'server_or_llm_calls': 0,
        'financial_validation_input_changed': False, 'sklearn_version': sklearn.__version__,
        'inference': 'median of exactly 2022,2023,2024 directional predictions',
        'entry_rule': 'net > 8bps and net - opposite-direction median > 8bps; unchanged risk structure',
        'trainer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'label_helper_sha256': hashlib.sha256(Path(__file__).with_name('train_execution_path_models.py').read_bytes()).hexdigest(),
        'ready_sha256': hashlib.sha256((args.input_dir / 'READY.json').read_bytes()).hexdigest(),
        'proxy_limitations': ['96-bar censor', 'no scene exits', 'no subsequent signal interference',
                              'training cost notional approximation'],
        'parameters': {'ridge_alpha': 200, 'trees': 24, 'max_depth': 2,
                       'min_leaf': 100, 'learning_rate': .05, 'seed': 20261110}}
    atomic_write_json(output / 'training-manifest.json', manifest)
    models = []
    with threadpool_limits(limits=1):
        for group, indices in GROUPS.items():
            for algorithm in ('ridge', 'boosted_tree'):
                for side in (1, -1):
                    for year in YEARS:
                        x = np.vstack(buckets[year, side][0]); y = np.concatenate(buckets[year, side][1])
                        selected = x[:, indices]
                        if algorithm == 'ridge':
                            scaler = StandardScaler().fit(selected)
                            fit = Ridge(alpha=200, solver='svd').fit(scaler.transform(selected), y)
                            folded = fit.coef_ / scaler.scale_
                            coefficients = np.zeros(18); coefficients[indices] = folded
                            model = {'algorithm': algorithm, 'coefficients': coefficients.tolist(),
                                'intercept': float(fit.intercept_ - folded @ scaler.mean_)}
                            reference = fit.predict(scaler.transform(selected[:64]))
                        else:
                            fit = GradientBoostingRegressor(loss='huber', n_estimators=24, learning_rate=.05,
                                max_depth=2, min_samples_leaf=100, random_state=20261110).fit(selected, y)
                            trees = []
                            for item in fit.estimators_.ravel():
                                tree = item.tree_
                                trees.append([[indices[int(tree.feature[n])] if tree.feature[n] >= 0 else -1,
                                    float(tree.threshold[n]), int(tree.children_left[n]), int(tree.children_right[n]),
                                    float(tree.value[n, 0, 0])] for n in range(tree.node_count)])
                            model = {'algorithm': algorithm, 'trees': trees,
                                'initial': float(fit.init_.predict(selected[:1])[0]), 'learning_rate': .05}
                            reference = fit.predict(selected[:64])
                        error = float(np.max(np.abs(reference - restored_prediction(model, x[:64]))))
                        if error > 1e-9:
                            raise ValueError('numeric export mismatch')
                        model.update(group=group, year=year, side=side, rows=len(y), export_max_abs_error=error)
                        models.append(model)
                        print('FROZEN_REGIME_MODEL', group, algorithm, side, year, len(y), error, flush=True)
    matrix = np.asarray(probes)
    package = {'manifest': manifest, 'models': models, 'probes': [{'features': row,
        'predictions': [float(median_prediction(models, matrix, group, algorithm, side)[i])
            for group in GROUPS for algorithm in ('ridge', 'boosted_tree') for side in (1, -1)]}
        for i, row in enumerate(probes)]}
    atomic_write_json(output / 'frozen-models.json', package)
    atomic_write_json(output / 'TRAINING_COMPLETE.json', {'models': len(models), 'strategy_classes': 8,
        'financial_holdout_evaluated': False, 'server_or_llm_calls': 0,
        'frozen_models_sha256': hashlib.sha256((output / 'frozen-models.json').read_bytes()).hexdigest()})


if __name__ == '__main__':
    main()
