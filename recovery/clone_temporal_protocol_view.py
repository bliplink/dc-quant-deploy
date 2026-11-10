"""Copy verified immutable market bytes into a separately protocol-bound READY view."""
import json
from pathlib import Path
import shutil

from recovery.strategy_recovery_common import atomic_write_json
from recovery.verify_fit_only_risk_contract import sha


def clone_view(source, output, protocol_path):
    if output.exists():
        raise ValueError('preserve old input views; a fresh directory is required')
    ready = json.loads((source / 'READY.json').read_text(encoding='utf-8'))
    protocol = json.loads(protocol_path.read_text(encoding='utf-8'))
    if (protocol.get('protocol_version') != 'temporal_source_research_v2'
            or ready.get('protocol_version') != 'temporal_source_research_v2'
            or ready.get('clock') != 'UTC' or ready.get('production_write') is not False
            or ready.get('begin') != protocol['primary_begin']
            or ready.get('primary_end_inclusive') != protocol['primary_end_inclusive']
            or ready.get('holdout_begin') != protocol['holdout_begin']
            or ready.get('end') != protocol['holdout_end_inclusive']
            or ready.get('minimum_holdout_calendar_days') != 62):
        raise ValueError('same completely separated market periods required')
    paths = []
    for symbol in ready['symbols']:
        for suffix, key in (('-15m.tsv', 'bars_sha256'), ('-scenes.tsv', 'scenes_sha256')):
            p = source / (symbol + suffix)
            if sha(p) != ready['files'][symbol][key]:
                raise ValueError('original frozen market bytes changed')
            paths.append((p, ready['files'][symbol][key]))
    output.mkdir(parents=True)
    for p, expected in paths:
        shutil.copyfile(p, output / p.name)
        if sha(output / p.name) != expected:
            raise ValueError('copied market bytes changed; preserve partial view')
    result = dict(ready, protocol_sha256=sha(protocol_path), cloned_source_ready_sha256=sha(source / 'READY.json'),
                  read_only_existing_data=True)
    atomic_write_json(output / 'READY.json', result)
    return result
