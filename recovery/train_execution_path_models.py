"""Freeze local entry models using pre-validation, execution-path profit labels.

Training is an economic proxy, not a substitute for the unchanged formal engine.
Unfilled/censored paths are excluded rather than assigned fictitious profit.
"""

import argparse
import hashlib
import json
from pathlib import Path

from recovery.strategy_recovery_common import atomic_write_json
from recovery.train_frozen_strategy_models import (
    TRAIN_BEGIN, TRAIN_END_EXCLUSIVE, feature_matrix, load_training_prefix, restored_prediction,
)


HORIZON = 96
STRIDE = 16
GROUPS = {
    'momentum': [0, 1, 2, 3, 6, 10, 16],
    'value': [4, 5, 7, 8, 9, 10, 17],
    'volatility': [0, 6, 7, 9, 10, 11, 16],
    'session': [0, 1, 7, 8, 10, 12, 13, 14, 15, 17],
}


def execution_features(frame):
    import numpy as np
    import pandas as pd
    basic, volatility = feature_matrix(frame)
    seconds = frame['time'].astype('int64').to_numpy() / 1e9
    daily = 2 * np.pi * np.mod(seconds, 86400) / 86400
    weekly = 2 * np.pi * np.mod(seconds, 604800) / 604800
    close = frame['close'].astype(float)
    absolute = close.diff().abs().rolling(32).sum()
    efficiency = (close - close.shift(32)) / absolute.clip(lower=1e-8)
    signed_volume = frame['volume'] * np.sign(close - frame['open'])
    flow = signed_volume.rolling(16).sum() / frame['volume'].rolling(16).sum().clip(lower=1e-8)
    return np.column_stack([basic, np.sin(daily), np.cos(daily), np.sin(weekly),
                            np.cos(weekly), efficiency, flow]), volatility


def path_label(prices, index, atr, side, horizon=HORIZON):
    """LIMIT valid next bar; risks start after fill; stop-first; close-based trail.

    Exactly mirrors the existing engine order within each bar, except for a
    finite training censor horizon and no scene exits. Those differences are
    deliberately left to the existing formal backtest, not hidden here.
    Returns (fee/stress-adjusted return, last observed index, reason), or None.
    """
    import math
    if side not in (-1, 1) or not math.isfinite(atr) or atr <= 0:
        raise ValueError('positive ATR and explicit direction required')
    entry = float(prices[index, 3])
    if index + horizon >= len(prices) or entry <= 0:
        return None
    next_bar = prices[index + 1]
    if (side > 0 and next_bar[2] > entry) or (side < 0 and next_bar[1] < entry):
        return None
    stop, take = entry - side * 1.5 * atr, entry + side * 3 * atr
    if stop <= 0 or take <= 0:
        return None
    for j in range(index + 2, index + horizon + 1):
        opened, high, low, close = prices[j]
        hit_stop = low <= stop if side > 0 else high >= stop
        hit_take = high >= take if side > 0 else low <= take
        if hit_stop or hit_take:
            exit_price = stop if hit_stop else take
            # 2/5 bps fees plus 4/5 bps stress, using entry/exit notionals.
            net = side * (exit_price / entry - 1) - .0006 - .001 * exit_price / entry
            return net, j, 'stop' if hit_stop else 'take'
        profit_pct = side * (close / entry - 1) * 100
        if profit_pct > .5:
            steps = math.floor((profit_pct - .5) / .2)
            protected = entry * (1 + side * (.5 + .2 * (steps - 1)) / 100)
            stop = max(stop, protected) if side > 0 else min(stop, protected)
    return None


def training_samples(frame, side, train_begin=TRAIN_BEGIN, strict_grid=False):
    import numpy as np
    import pandas as pd
    x, volatility = execution_features(frame)
    prices = frame[['open', 'high', 'low', 'close']].to_numpy(dtype=float)
    eligible = ((frame['time'] >= pd.Timestamp(train_begin, tz='UTC'))
                & (np.arange(len(frame)) >= 200) & (np.arange(len(frame)) % STRIDE == 0)
                & np.isfinite(x).all(axis=1))
    xs, ys, observed = [], [], []
    for i in np.flatnonzero(eligible):
        # Require the ENTIRE potential observation horizon before validation.
        if i + HORIZON >= len(frame) or frame.iloc[i + HORIZON]['time'] >= pd.Timestamp(TRAIN_END_EXCLUSIVE, tz='UTC'):
            continue
        if strict_grid and (frame.iloc[i + HORIZON]['time'] - frame.iloc[i - 199]['time']
                            != pd.Timedelta(minutes=(HORIZON + 199) * 15)):
            continue
        atr = volatility[i] * prices[i, 3]
        if atr * 3 / prices[i, 3] < .0048:
            continue
        label = path_label(prices, i, atr, side)
        if label is None:
            continue
        net, end, reason = label
        xs.append(x[i]); ys.append(net / volatility[i]); observed.append((int(i), int(end), reason))
    if not xs:
        raise ValueError('no fully observed execution labels')
    return np.asarray(xs), np.asarray(ys), observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if (output / 'TRAINING_COMPLETE.json').exists():
        raise ValueError('already frozen; never retrain an inspected cohort')
    import numpy as np
    import sklearn
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    from threadpoolctl import threadpool_limits
    ready = json.loads((args.input_dir / 'READY.json').read_text(encoding='utf-8'))
    sides = {side: ([], []) for side in (1, -1)}
    evidence, probes = [], []
    output.mkdir(parents=True, exist_ok=True)
    for symbol, files in sorted(ready['files'].items()):
        path = args.input_dir / (symbol + '-15m.tsv')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != files['bars_sha256']:
            raise ValueError('input hash mismatch: ' + symbol)
        frame = load_training_prefix(path)
        for side in (1, -1):
            x, y, observed = training_samples(frame, side)
            sides[side][0].append(x); sides[side][1].append(y)
            evidence.append({'symbol': symbol, 'side': side, 'samples': len(y), 'bars_sha256': digest,
                'last_observed_label_time': str(frame.iloc[max(row[1] for row in observed)]['time'])})
            if not probes:
                probes = x[:16].tolist()
    manifest = {'version': 'execution_path_v1', 'train_begin': TRAIN_BEGIN,
        'train_end_exclusive': TRAIN_END_EXCLUSIVE, 'horizon_bars': HORIZON, 'stride_bars': STRIDE,
        'overlapping_training_labels': True, 'independence_or_significance_claim': False,
        'groups': GROUPS, 'input': evidence, 'server_or_llm_calls': 0,
        'sklearn_version': sklearn.__version__, 'features': 18,
        'trainer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'feature_source_sha256': hashlib.sha256(Path(__file__).with_name('train_frozen_strategy_models.py').read_bytes()).hexdigest(),
        'ready_sha256': hashlib.sha256((args.input_dir / 'READY.json').read_bytes()).hexdigest(),
        'proxy_limitations': ['96-bar censor', 'no scene exits', 'no subsequent signal interference'],
        'model_parameters': {'ridge_alpha': 200, 'trees': 24, 'max_depth': 2,
                             'min_leaf': 100, 'learning_rate': .05, 'seed': 20261110}}
    atomic_write_json(output / 'training-manifest.json', manifest)
    models = []
    with threadpool_limits(limits=1):
        for group, indices in GROUPS.items():
            for algorithm in ('ridge', 'boosted_tree'):
                for side in (1, -1):
                    x, y = np.vstack(sides[side][0]), np.concatenate(sides[side][1])
                    selected = x[:, indices]
                    if algorithm == 'ridge':
                        scaler = StandardScaler().fit(selected)
                        fit = Ridge(alpha=200, solver='svd').fit(scaler.transform(selected), y)
                        folded = fit.coef_ / scaler.scale_
                        weights = np.zeros(18); weights[indices] = folded
                        model = {'algorithm': algorithm, 'coefficients': weights.tolist(),
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
                        raise ValueError('standalone numerical mismatch')
                    model.update(group=group, side=side, rows=len(y), export_max_abs_error=error)
                    models.append(model)
                    print('FROZEN_EXECUTION_MODEL', group, algorithm, side, len(y), error, flush=True)
    package = {'manifest': manifest, 'models': models, 'probes': [
        {'features': row, 'predictions': [float(restored_prediction(model, np.asarray(row)[None, :])[0])
                                        for model in models]} for row in probes]}
    atomic_write_json(output / 'frozen-models.json', package)
    atomic_write_json(output / 'TRAINING_COMPLETE.json', {'models': len(models),
        'financial_holdout_evaluated': False, 'server_or_llm_calls': 0,
        'frozen_models_sha256': hashlib.sha256((output / 'frozen-models.json').read_bytes()).hexdigest()})


if __name__ == '__main__':
    main()
