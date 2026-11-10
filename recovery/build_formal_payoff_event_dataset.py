"""New ATR labels from immutable structural events and pre-validation bars only."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from recovery.formal_payoff_labels import HORIZON, LABEL_SCHEMA, path_label
from recovery.strategy_recovery_common import atomic_write_json
from recovery.train_execution_path_models import execution_features
from recovery.train_frozen_strategy_models import load_training_prefix
from recovery.train_structural_meta_models import FAMILIES


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sample_events(frame, events):
    import numpy as np
    import pandas as pd
    x, volatility = execution_features(frame)
    prices = frame[['open', 'high', 'low', 'close']].to_numpy(dtype=float)
    times = frame['time'].astype('int64').to_numpy() // 1000000
    years = frame['time'].dt.year.to_numpy()
    cutoff = int(pd.Timestamp('2024-12-15', tz='UTC').timestamp() * 1000)
    last, seen, selected = {}, {}, []
    for row in events:
        family, side, i = row['family'], int(row['side']), int(row['index'])
        if (family not in FAMILIES or side not in (-1, 1) or not 199 <= i < len(frame)
                or int(row['time']) != times[i]):
            raise ValueError('event identity differs from frozen training bars')
        key = family, side
        if i <= seen.get(key, -1000):
            raise ValueError('duplicate or out-of-order event')
        seen[key] = i
        if i - last.get(key, -1000) < 16:
            continue
        last[key] = i
        if (i + HORIZON >= len(frame) or times[i + HORIZON] >= cutoff
                or times[i + HORIZON] - times[i - 199] != (HORIZON + 199) * 15 * 60000
                or not np.isfinite(x[i]).all()):
            continue
        label = path_label(prices, i, volatility[i] * prices[i, 3], side)
        if label is None:
            continue
        net, end, reason = label
        if years[end] != years[i]:
            continue
        selected.append((family, side, x[i], net / volatility[i], years[i], i, end))
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('input-dir', 'parent-model-dir', 'oracle-audit', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if (args.output_dir / 'READY.json').exists():
        raise ValueError('dataset already frozen')
    import numpy as np
    ready = json.loads((args.input_dir / 'READY.json').read_text(encoding='utf-8'))
    parent = json.loads((args.parent_model_dir / 'training-manifest.json').read_text(encoding='utf-8'))
    complete = json.loads((args.parent_model_dir / 'TRAINING_COMPLETE.json').read_text(encoding='utf-8'))
    audit = json.loads(args.oracle_audit.read_text(encoding='utf-8'))
    helper_sha = sha(Path(__file__).with_name('formal_payoff_labels.py'))
    if (ready.get('purpose') != 'training_only' or ready.get('train_end_exclusive') != '2024-12-15'
            or sha(args.input_dir / 'READY.json') != parent['ready_sha256']
            or sha(args.parent_model_dir / 'frozen-models.json') != complete['frozen_models_sha256']
            or audit.get('label_schema') != LABEL_SCHEMA or audit.get('passed') is not True
            or audit.get('financial_data_read') is not False
            or audit.get('label_helper_sha256') != helper_sha):
        raise ValueError('training input, parent, or formal oracle contract changed')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for symbol, record in sorted(ready['files'].items()):
        bars = args.input_dir / (symbol + '-15m.tsv')
        event_dir = args.parent_model_dir / 'events' / symbol
        events, checkpoint = event_dir / 'events.tsv', event_dir / 'checkpoint.json'
        saved = json.loads(checkpoint.read_text(encoding='utf-8'))
        if (sha(bars) != record['bars_sha256'] or saved['frozen']['bars_sha256'] != record['bars_sha256']
                or saved['frozen']['base_rules_sha256'] != parent['base_rules_sha256']
                or saved['events_sha256'] != sha(events)):
            raise ValueError('immutable event provenance mismatch: ' + symbol)
        frozen = {'bars_sha256': sha(bars), 'events_sha256': sha(events),
            'historical_checkpoint_sha256': sha(checkpoint), 'label_helper_sha256': helper_sha,
            'oracle_audit_sha256': sha(args.oracle_audit), 'builder_sha256': sha(Path(__file__))}
        output, status = args.output_dir / (symbol + '.npz'), args.output_dir / (symbol + '.json')
        if status.exists():
            previous = json.loads(status.read_text(encoding='utf-8'))
            if previous['frozen'] != frozen or previous['dataset_sha256'] != sha(output):
                raise ValueError('derived training checkpoint changed')
            outputs[symbol] = previous
            continue
        frame = load_training_prefix(bars)
        with events.open(encoding='utf-8') as stream:
            rows = sample_events(frame, csv.DictReader(stream, delimiter='\t'))
        if not rows:
            raise ValueError('no observed labels')
        y = np.asarray([row[3] for row in rows])
        np.savez_compressed(output, x=np.vstack([row[2] for row in rows]), y=y,
            years=np.asarray([row[4] for row in rows], dtype=np.int16),
            families=np.asarray([row[0] for row in rows]), sides=np.asarray([row[1] for row in rows], dtype=np.int8),
            signal_indices=np.asarray([row[5] for row in rows], dtype=np.int32),
            label_indices=np.asarray([row[6] for row in rows], dtype=np.int32))
        info = {'frozen': frozen, 'dataset_sha256': sha(output), 'rows': len(rows),
            'negative_labels': int((y < 0).sum()), 'positive_labels': int((y > 0).sum()),
            'last_label_time': str(frame.iloc[max(row[6] for row in rows)]['time'])}
        atomic_write_json(status, info)
        outputs[symbol] = info
        atomic_write_json(args.output_dir / 'status.json', {'completed_symbols': len(outputs),
            'total_symbols': len(ready['files']), 'training_only': True, 'server_or_llm_calls': 0})
        print('FORMAL_PAYOFF_EVENTS', symbol, len(rows), 'losses', info['negative_labels'], flush=True)
    atomic_write_json(args.output_dir / 'READY.json', {'purpose': 'training_events_only',
        'training_cutoff_exclusive': '2024-12-15', 'base_rules_sha256': parent['base_rules_sha256'],
        'parent_model_sha256': complete['frozen_models_sha256'], 'files': outputs,
        'label_schema': LABEL_SCHEMA, 'label_helper_sha256': helper_sha,
        'oracle_audit_sha256': sha(args.oracle_audit), 'oracle_passed': True,
        'financial_validation_read': False, 'server_or_llm_calls': 0,
        'loss_labels_clipped_or_dropped': False})


if __name__ == '__main__':
    main()
