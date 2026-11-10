"""New conditional mean-payoff hypothesis, not a retune of inspected forward PnL.

Squared-error training targets the complete fee-adjusted conditional expectation,
not a robust centre. Risk, acceptance buffer, and qualification gates stay fixed.
"""

import argparse
import hashlib
import json
from pathlib import Path

from recovery.strategy_recovery_common import atomic_write_json
from recovery.train_frozen_strategy_models import restored_prediction
from recovery.train_structural_meta_models import FAMILIES, balanced_year_weights


def fit_expectancy(x, y, weights):
    import numpy as np
    from sklearn.ensemble import GradientBoostingRegressor
    if not np.isfinite(x).all() or not np.isfinite(y).all() or not np.isfinite(weights).all() or (weights <= 0).any():
        raise ValueError('finite observations and strictly positive year weights required')
    fit = GradientBoostingRegressor(loss='squared_error', n_estimators=24, learning_rate=.05,
        max_depth=2, min_samples_leaf=50, random_state=20261110).fit(x, y, sample_weight=weights)
    trees = []
    for item in fit.estimators_.ravel():
        tree = item.tree_
        trees.append([[int(tree.feature[n]), float(tree.threshold[n]), int(tree.children_left[n]),
                       int(tree.children_right[n]), float(tree.value[n, 0, 0])] for n in range(tree.node_count)])
    model = {'algorithm': 'boosted_tree', 'trees': trees, 'learning_rate': .05,
             'initial': float(fit.init_.predict(x[:1])[0]), 'loss': 'squared_error'}
    return fit, model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if (args.output_dir / 'TRAINING_COMPLETE.json').exists():
        raise ValueError('models already frozen; do not overwrite')
    import numpy as np
    import sklearn
    from threadpoolctl import threadpool_limits
    ready = json.loads((args.dataset_dir / 'READY.json').read_text(encoding='utf-8'))
    if ready.get('purpose') != 'training_events_only' or ready.get('training_cutoff_exclusive') != '2024-12-15':
        raise ValueError('explicitly training-only event dataset required')
    arrays = []
    for symbol, record in sorted(ready['files'].items()):
        path = args.dataset_dir / (symbol + '.npz')
        if hashlib.sha256(path.read_bytes()).hexdigest() != record['dataset_sha256']:
            raise ValueError('frozen event arrays changed')
        with np.load(path, allow_pickle=False) as data:
            arrays.append({name: data[name] for name in ('x', 'y', 'years', 'families', 'sides')})
    data = {name: np.concatenate([row[name] for row in arrays]) for name in arrays[0]}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {'version': 'structural_expectancy_v1', 'families': list(FAMILIES),
        'base_rules_sha256': ready['base_rules_sha256'], 'features': 18,
        'training_cutoff_exclusive': '2024-12-15', 'year_balancing': 'equal aggregate weight per 2022/2023/2024',
        'prediction_target': 'conditional arithmetic mean of all retained net-payoff labels',
        'loss': 'squared_error', 'loss_labels_clipped_or_dropped': False,
        'parameters': {'trees': 24, 'max_depth': 2, 'min_leaf': 50, 'learning_rate': .05,
                       'seed': 20261110, 'minimum_labels': 200, 'minimum_labels_each_year': 20},
        'acceptance_rule': 'original structural event AND predicted net payoff > 8bps',
        'server_or_llm_calls': 0, 'financial_holdout_evaluated': False,
        'dataset_ready_sha256': hashlib.sha256((args.dataset_dir / 'READY.json').read_bytes()).hexdigest(),
        'parent_model_sha256': ready['parent_model_sha256'],
        'trainer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'sklearn_version': sklearn.__version__, 'overlapping_training_labels': True,
        'independence_or_significance_claim': False,
        'proxy_limitations': ['96-bar censor', 'no scene exits', 'no subsequent signal interference', 'cost notional approximation']}
    atomic_write_json(args.output_dir / 'training-manifest.json', manifest)
    models, skipped, diagnostics = [], [], []
    with threadpool_limits(limits=1):
        for family in FAMILIES:
            cases = {}
            for side in (1, -1):
                keep = (data['families'] == family) & (data['sides'] == side)
                years = data['years'][keep]
                counts = {year: int((years == year).sum()) for year in (2022, 2023, 2024)}
                if keep.sum() < 200 or min(counts.values()) < 20:
                    skipped.append({'family': family, 'side': side, 'rows': int(keep.sum()), 'year_counts': counts})
                cases[side] = keep
            if any(record['family'] == family for record in skipped):
                continue
            for side, keep in cases.items():
                x, y, years = data['x'][keep], data['y'][keep], data['years'][keep]
                weights = balanced_year_weights(years)
                fit, model = fit_expectancy(x, y, weights)
                replay = restored_prediction(model, x[:64])
                error = float(np.max(np.abs(fit.predict(x[:64]) - replay)))
                if error > 1e-9:
                    raise ValueError('standalone payoff inference mismatch')
                model.update(family=family, side=side, rows=len(y), export_max_abs_error=error)
                models.append(model)
                diagnostics.append({'family': family, 'side': side, 'rows': len(y),
                    'positive_labels': int((y > 0).sum()), 'negative_labels': int((y < 0).sum()),
                    'year_balanced_mean': float(np.average(y, weights=weights)), 'median': float(np.median(y)),
                    'minimum': float(y.min()), 'maximum': float(y.max()), 'all_loss_labels_retained': True})
                print('FROZEN_EXPECTANCY', family, side, len(y), error, flush=True)
    probes = data['x'][:8]
    package = {'manifest': manifest, 'models': models, 'skipped': skipped,
        'training_distribution': diagnostics, 'probes': [
            {'features': row.tolist(), 'predictions': [float(restored_prediction(m, row[None, :])[0]) for m in models]}
            for row in probes]}
    atomic_write_json(args.output_dir / 'frozen-models.json', package)
    atomic_write_json(args.output_dir / 'TRAINING_COMPLETE.json', {'models': len(models),
        'strategy_classes': len(models) // 2, 'skipped': skipped, 'server_or_llm_calls': 0,
        'financial_holdout_evaluated': False,
        'frozen_models_sha256': hashlib.sha256((args.output_dir / 'frozen-models.json').read_bytes()).hexdigest()})


if __name__ == '__main__':
    main()
