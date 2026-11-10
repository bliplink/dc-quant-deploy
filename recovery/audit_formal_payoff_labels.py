"""Synthetic-bar oracle: compare new training labels with actual SIM risk/cost classes."""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from recovery.formal_payoff_labels import path_label, LABEL_SCHEMA
from recovery.local_strategy_backtest import java_classpath
from recovery.strategy_recovery_common import atomic_write_json


def fixtures():
    import numpy as np
    cases = []
    for side in (1, -1):
        for mode in ('stop', 'take', 'collision', 'trail_boundary', 'floor', 'unfilled', 'censored'):
            atr = .1 if mode == 'floor' else 1.
            rows = np.tile([100., 100.01, 99.99, 100.], (5, 1))
            if mode in ('stop', 'collision'):
                rows[1] = [100, 110, 90, 100]  # fill bar risks are not replayed
                rows[2] = [100, 104 if mode == 'collision' or side < 0 else 100.1,
                           96 if mode == 'collision' or side > 0 else 99.9, 100]
            elif mode == 'take':
                rows[2] = [100, 104 if side > 0 else 100.1, 96 if side < 0 else 99.9, 100]
            elif mode == 'trail_boundary':
                rows[2] = [100, 102.6 if side > 0 else 100.01,
                           97.4 if side < 0 else 99.99, 100 + side * 2.5]
                rows[3] = [100 + side * 2.5, 102.6 if side > 0 else 98.1,
                           101.9 if side > 0 else 97.4, 100 + side * 2.1]
            elif mode == 'floor':
                # With 3ATR take below the .5% EMS floor, take must occur first.
                rows[2] = [100, 100.31 if side > 0 else 100.01,
                           99.69 if side < 0 else 99.99, 100 + side * .3]
            elif mode == 'unfilled':
                rows[1] = [101, 102, 101, 101] if side > 0 else [99, 99, 98, 99]
                rows[2] = [100, 104, 96, 100]
            cases.append((mode + '_' + str(side), side, atr, rows))
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--indsvr-repo', type=Path, required=True)
    parser.add_argument('--sim-repo', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cases = fixtures()
    input_path = args.output_dir / 'synthetic-fixtures.tsv'
    input_path.write_text('\n'.join(name + '\t' + str(side) + '\t' + str(atr) + '\t' +
        ';'.join(':'.join(str(v) for v in row) for row in rows) for name, side, atr, rows in cases) + '\n', encoding='utf-8')
    cp = os.pathsep.join([str(args.indsvr_repo / 'target/test-classes'),
                         str(args.indsvr_repo / 'target/classes'), java_classpath(args.sim_repo)])
    result = subprocess.run(['java', '-cp', cp,
        'com.app.dc.service.strategy.research.FormalPayoffOracleCli', str(input_path)],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
    (args.output_dir / 'oracle.stdout.log').write_text(result.stdout, encoding='utf-8')
    (args.output_dir / 'oracle.stderr.log').write_text(result.stderr, encoding='utf-8')
    result.check_returncode()
    actual = {line.split('\t')[0]: line.split('\t')[1:] for line in result.stdout.splitlines()}
    evidence = []
    for name, side, atr, rows in cases:
        expected = path_label(rows, 0, atr, side, horizon=4)
        observed = actual[name]
        passed = observed == ['NONE'] if expected is None else (
            observed != ['NONE'] and abs(expected[0] - float(observed[0])) < 1e-10
            and expected[1] == int(observed[1])
            and expected[2] == ('take' if observed[2] == 'take_profit' else 'stop'))
        evidence.append({'case': name, 'training_proxy': expected, 'formal': observed, 'passed': passed})
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    class_root = args.sim_repo / 'target/classes/com/app/dc/service/simulation'
    audit = {'label_schema': LABEL_SCHEMA, 'cases': evidence, 'passed': all(row['passed'] for row in evidence),
        'trade_service_class_sha256': digest(class_root / 'BacktestTradeService.class'),
        'stress_service_class_sha256': digest(class_root / 'runtime/ExecutionStressService.class'),
        'label_helper_sha256': digest(Path(__file__).with_name('formal_payoff_labels.py')),
        'financial_data_read': False, 'server_or_llm_calls': 0}
    atomic_write_json(args.output_dir / 'audit.json', audit)
    print('FORMAL_PAYOFF_ORACLE', len(evidence), 'passed', sum(row['passed'] for row in evidence), flush=True)
    if not audit['passed']:
        raise ValueError('training label differs from actual formal oracle')


if __name__ == '__main__':
    main()
