"""Freeze reusable training-only structural event labels from immutable prior events.

No event regeneration, validation PnL, server access, runtime change, or LLM call.
The historical compiler hashes in existing event checkpoints stay historical;
their output hashes and source/bar contracts are checked before reuse.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from recovery.strategy_recovery_common import atomic_write_json
from recovery.train_frozen_strategy_models import load_training_prefix
from recovery.train_structural_meta_models import event_samples


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--parent-model-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if (args.output_dir / 'READY.json').exists():
        raise ValueError('training event dataset is already frozen')
    import numpy as np
    ready = json.loads((args.input_dir / 'READY.json').read_text(encoding='utf-8'))
    parent = json.loads((args.parent_model_dir / 'training-manifest.json').read_text(encoding='utf-8'))
    complete = json.loads((args.parent_model_dir / 'TRAINING_COMPLETE.json').read_text(encoding='utf-8'))
    if (ready.get('purpose') != 'training_only' or ready.get('train_end_exclusive') != '2024-12-15'
            or sha(args.input_dir / 'READY.json') != parent['ready_sha256']
            or sha(args.parent_model_dir / 'frozen-models.json') != complete['frozen_models_sha256']):
        raise ValueError('parent model or training input contract changed')
    if sha(Path(__file__).with_name('train_structural_meta_models.py')) != parent['trainer_sha256']:
        raise ValueError('event sampling implementation changed; do not silently rebuild labels')
    if sha(Path(__file__).with_name('train_execution_path_models.py')) != parent['label_helper_sha256']:
        raise ValueError('training execution semantics changed')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for symbol, record in sorted(ready['files'].items()):
        bars_path = args.input_dir / (symbol + '-15m.tsv')
        event_dir = args.parent_model_dir / 'events' / symbol
        event_path, checkpoint_path = event_dir / 'events.tsv', event_dir / 'checkpoint.json'
        checkpoint = json.loads(checkpoint_path.read_text(encoding='utf-8'))
        if (sha(bars_path) != record['bars_sha256']
                or checkpoint['frozen']['bars_sha256'] != record['bars_sha256']
                or checkpoint['frozen']['base_rules_sha256'] != parent['base_rules_sha256']
                or sha(event_path) != checkpoint['events_sha256']):
            raise ValueError('frozen event provenance changed: ' + symbol)
        frozen = {'bars_sha256': record['bars_sha256'], 'events_sha256': sha(event_path),
                  'checkpoint_sha256': sha(checkpoint_path), 'parent_manifest_sha256': sha(args.parent_model_dir / 'training-manifest.json')}
        output_path = args.output_dir / (symbol + '.npz')
        output_checkpoint = args.output_dir / (symbol + '.json')
        if output_checkpoint.exists():
            saved = json.loads(output_checkpoint.read_text(encoding='utf-8'))
            if saved['frozen'] != frozen or sha(output_path) != saved['dataset_sha256']:
                raise ValueError('changed derived event dataset')
            outputs[symbol] = saved
            continue
        frame = load_training_prefix(bars_path)
        with event_path.open(encoding='utf-8') as stream:
            selected = event_samples(frame, csv.DictReader(stream, delimiter='\t'))
        rows = [(family, side, *row) for (family, side), values in sorted(selected.items()) for row in values]
        x = np.vstack([row[2] for row in rows])
        y = np.asarray([row[3] for row in rows])
        years = np.asarray([row[4] for row in rows], dtype=np.int16)
        np.savez_compressed(output_path, x=x, y=y, years=years,
            families=np.asarray([row[0] for row in rows]), sides=np.asarray([row[1] for row in rows], dtype=np.int8),
            signal_indices=np.asarray([row[5] for row in rows], dtype=np.int32),
            label_indices=np.asarray([row[6] for row in rows], dtype=np.int32))
        info = {'frozen': frozen, 'dataset_sha256': sha(output_path), 'rows': len(rows),
                'negative_labels': int((y < 0).sum()), 'positive_labels': int((y > 0).sum()),
                'minimum_label': float(y.min()), 'maximum_label': float(y.max()),
                'last_label_time': str(frame.iloc[max(row[6] for row in rows)]['time']),
                'server_or_llm_calls': 0, 'financial_validation_read': False}
        atomic_write_json(output_checkpoint, info)
        outputs[symbol] = info
        atomic_write_json(args.output_dir / 'status.json', {'completed_symbols': len(outputs), 'total_symbols': len(ready['files'])})
        print('EVENT_DATASET', symbol, len(rows), 'losses', info['negative_labels'], flush=True)
    atomic_write_json(args.output_dir / 'READY.json', {'purpose': 'training_events_only',
        'training_cutoff_exclusive': '2024-12-15', 'base_rules_sha256': parent['base_rules_sha256'],
        'parent_model_sha256': complete['frozen_models_sha256'], 'files': outputs,
        'sampler_sha256': parent['trainer_sha256'], 'label_helper_sha256': parent['label_helper_sha256'],
        'server_or_llm_calls': 0, 'financial_validation_read': False, 'loss_labels_clipped_or_dropped': False})


if __name__ == '__main__':
    main()
