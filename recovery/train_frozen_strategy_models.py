"""Train fixed local models strictly before the existing research validation period.

No strategy financial holdout is evaluated here, and no server/LLM is contacted.
The coefficients/trees are frozen for later self-contained Java source export.
"""

import argparse
import hashlib
import json
from pathlib import Path

from recovery.strategy_recovery_common import atomic_write_json


TRAIN_BEGIN = '2024-08-15'
TRAIN_END_EXCLUSIVE = '2024-12-15'
HORIZON = 16
STRIDE = 16
GROUPS = {
    'momentum': [0, 1, 2, 3, 6, 10],
    'value': [4, 5, 7, 8, 9, 10],
    'volatility': [0, 6, 7, 9, 10, 11],
    'flow': [0, 1, 7, 8, 9, 10],
}


def load_training_prefix(path):
    import pandas as pd
    names = ['time', 'open', 'high', 'low', 'close', 'volume']
    parts = []
    for chunk in pd.read_csv(path, sep='\t', names=names, chunksize=10000):
        if str(chunk.iloc[0]['time'])[:10] >= TRAIN_END_EXCLUSIVE:
            break
        older = chunk.loc[chunk['time'].str.slice(0, 10) < TRAIN_END_EXCLUSIVE].copy()
        parts.append(older)
        if len(older) != len(chunk):
            break
    if not parts:
        raise ValueError('no pre-validation training history: ' + str(path))
    frame = pd.concat(parts, ignore_index=True)
    frame['time'] = pd.to_datetime(frame['time'], format='%Y-%m-%d %H:%M:%S.%f', utc=True)
    if not frame['time'].is_monotonic_increasing or frame['time'].duplicated().any():
        raise ValueError('training prefix is not canonical chronological data')
    return frame


def feature_matrix(frame):
    import numpy as np
    import pandas as pd
    close, high, low, volume, opened = (frame[name].astype(float) for name in
                                       ('close', 'high', 'low', 'volume', 'open'))
    tr = pd.concat([high - low, (high - close.shift(1)).abs(),
                    (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr20 = tr.rolling(20).mean()
    volatility = (atr20 / close).clip(lower=1e-8)
    typical = (high + low + close) / 3
    vwap = (typical * volume).rolling(64).sum() / volume.rolling(64).sum().clip(lower=1e-8)
    candle_range = (high - low).clip(lower=close * 1e-8)
    values = [np.log(close / close.shift(lag)) / (volatility * divisor)
              for lag, divisor in ((1, 1), (4, 2), (16, 4), (64, 8))]
    values += [(close - close.rolling(32).mean()) / (atr20 * 3),
               (close - vwap) / (atr20 * 4),
               (tr.rolling(6).mean() / tr.rolling(32).mean().clip(lower=1e-8) - 1) * 2,
               (close - opened) / atr20.clip(lower=1e-8),
               (close - low) / candle_range * 2 - 1,
               (np.minimum(opened, close) - low - (high - np.maximum(opened, close))) / candle_range,
               np.log(volume.clip(lower=1e-8) / volume.shift(1).rolling(20).mean().clip(lower=1e-8)),
               np.log(volatility / 0.003)]
    matrix = np.column_stack([value.to_numpy() for value in values])
    return np.clip(matrix, -4, 4), volatility.to_numpy()


def samples(frame):
    import numpy as np
    import pandas as pd
    x, volatility = feature_matrix(frame)
    close = frame['close'].astype(float).to_numpy()
    label = np.full(len(frame), np.nan)
    label[:-HORIZON] = np.log(close[HORIZON:] / close[:-HORIZON]) / volatility[:-HORIZON]
    observed_end = frame['time'].shift(-HORIZON)
    valid = ((frame['time'] >= pd.Timestamp(TRAIN_BEGIN, tz='UTC'))
             & (observed_end < pd.Timestamp(TRAIN_END_EXCLUSIVE, tz='UTC'))
             & (np.arange(len(frame)) >= 200) & (np.arange(len(frame)) % STRIDE == 0)
             & np.isfinite(label) & np.isfinite(x).all(axis=1))
    if not valid.any():
        raise ValueError('no complete non-overlapping training labels')
    selected = np.flatnonzero(valid)
    return x[selected], np.clip(label[selected], -8, 8), selected


def restored_prediction(model, rows):
    import numpy as np
    if model['algorithm'] == 'ridge':
        return rows @ np.asarray(model['coefficients']) + model['intercept']
    result = np.full(len(rows), model['initial'])
    # sklearn tree inference compares float32 features, even for float64 training input.
    rounded = rows.astype(np.float32)
    for tree in model['trees']:
        for r, row in enumerate(rounded):
            node = 0
            while tree[node][0] >= 0:
                feature, threshold, left, right, _ = tree[node]
                # NumPy 2.x weak scalar promotion may round the double threshold
                # down to float32. sklearn/Java instead promote the input to double.
                node = left if float(row[feature]) <= threshold else right
            result[r] += model['learning_rate'] * tree[node][4]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if (output / 'TRAINING_COMPLETE.json').exists():
        raise ValueError('models are already frozen; do not retrain an inspected cohort')
    import numpy as np
    import sklearn
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    from threadpoolctl import threadpool_limits
    ready = json.loads((args.input_dir / 'READY.json').read_text(encoding='utf-8'))
    all_x, all_y, evidence = [], [], []
    output.mkdir(parents=True, exist_ok=True)
    for symbol, files in sorted(ready['files'].items()):
        path = args.input_dir / (symbol + '-15m.tsv')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != files['bars_sha256']:
            raise ValueError('input READY hash mismatch: ' + symbol)
        frame = load_training_prefix(path)
        x, y, indices = samples(frame)
        all_x.append(x); all_y.append(y)
        evidence.append({'symbol': symbol, 'bars_sha256': digest, 'samples': len(y),
                         'first_signal_time': str(frame.iloc[indices[0]]['time']),
                         'last_label_time': str(frame.iloc[indices[-1] + HORIZON]['time'])})
    x, y = np.vstack(all_x), np.concatenate(all_y)
    manifest = {'version': 'frozen_supervised_v1', 'train_begin': TRAIN_BEGIN,
                'train_end_exclusive': TRAIN_END_EXCLUSIVE, 'label_horizon_bars': HORIZON,
                'sampling_stride_bars': STRIDE, 'overlapping_training_labels': False,
                'model_groups': GROUPS, 'rows': len(y), 'columns': x.shape[1], 'input': evidence,
                'sklearn_version': sklearn.__version__, 'server_or_llm_calls': 0,
                'trainer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'ready_sha256': hashlib.sha256((args.input_dir / 'READY.json').read_bytes()).hexdigest()}
    atomic_write_json(output / 'training-manifest.json', manifest)
    models = []
    with threadpool_limits(limits=1):
        for group, indices in GROUPS.items():
            for algorithm in ('ridge', 'boosted_tree'):
                selected = x[:, indices]
                if algorithm == 'ridge':
                    scaler = StandardScaler().fit(selected)
                    estimator = Ridge(alpha=200, solver='svd').fit(scaler.transform(selected), y)
                    coefficients = np.zeros(x.shape[1])
                    folded = estimator.coef_ / scaler.scale_
                    coefficients[indices] = folded
                    model = {'algorithm': algorithm, 'group': group,
                             'coefficients': coefficients.tolist(),
                             'intercept': float(estimator.intercept_ - folded @ scaler.mean_)}
                    reference = estimator.predict(scaler.transform(selected[:64]))
                else:
                    estimator = GradientBoostingRegressor(loss='huber', n_estimators=24, learning_rate=0.05,
                        max_depth=2, min_samples_leaf=100, random_state=20261110).fit(selected, y)
                    trees = []
                    for item in estimator.estimators_.ravel():
                        tree = item.tree_
                        trees.append([[indices[int(tree.feature[n])] if tree.feature[n] >= 0 else -1,
                            float(tree.threshold[n]), int(tree.children_left[n]), int(tree.children_right[n]),
                            float(tree.value[n, 0, 0])] for n in range(tree.node_count)])
                    model = {'algorithm': algorithm, 'group': group, 'trees': trees,
                             'initial': float(estimator.init_.predict(selected[:1])[0]), 'learning_rate': 0.05}
                    reference = estimator.predict(selected[:64])
                replay = restored_prediction(model, x[:64])
                difference = float(np.max(np.abs(reference - replay)))
                if difference > 1e-9:
                    raise ValueError('standalone model export differs: ' + str(difference))
                model.update(rows=len(y), export_max_abs_error=difference,
                             forecast_error_floor=float(np.std(y - restored_prediction(model, x)) / np.sqrt(len(y))))
                models.append(model)
                print('FROZEN_MODEL', group, algorithm, 'rows', len(y), 'export_error', difference, flush=True)
    package = {'manifest': manifest, 'models': models,
               'probes': [{'features': row.tolist(), 'predictions': [float(restored_prediction(m, row[None, :])[0])
                         for m in models]} for row in x[:16]]}
    atomic_write_json(output / 'frozen-models.json', package)
    atomic_write_json(output / 'TRAINING_COMPLETE.json', {'models': len(models), 'training_rows': len(y),
        'financial_holdout_evaluated': False, 'server_or_llm_calls': 0,
        'frozen_models_sha256': hashlib.sha256((output / 'frozen-models.json').read_bytes()).hexdigest()})


if __name__ == '__main__':
    main()
