"""Fast source-rule diagnostics before expensive individual compilation/parity.

Does not replace a SOURCE_CONTRACT_COMPLETE proof or waive individual checks.
"""
import argparse
import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path

from recovery.export_representative_candidate import export_candidate
from recovery.local_strategy_backtest import java_classpath
from recovery.strategy_recovery_common import atomic_write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('campaign-dir', 'indsvr-repo', 'sim-repo', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    campaign = json.loads((args.campaign_dir / 'campaign.json').read_text(encoding='utf-8'))
    rows = []
    for item in campaign['catalog']:
        folder, name = export_candidate(args.campaign_dir, args.indsvr_repo,
            args.output_dir / 'frozen', 'BTCUSDT', 'trend', item['hypothesis'])
        rows.append('\t'.join((item['hypothesis'], str(folder / 'GeneratedStrategy.java'),
                              'Frozen local strategy ' + item['hypothesis'], name)))
    manifest = args.output_dir / 'sources.tsv'
    manifest.write_text('\n'.join(rows) + '\n', encoding='utf-8')
    classes = args.output_dir / 'audit-classes'
    classes.mkdir(exist_ok=True)
    cp = os.pathsep.join([str(args.indsvr_repo / 'target/classes'), java_classpath(args.sim_repo)])
    subprocess.run(['javac', '-encoding', 'UTF-8', '-cp', cp, '-d', str(classes),
                    str(Path(__file__).with_name('java') / 'StrategySourceContractAuditCli.java')], check=True)
    result = subprocess.run(['java', '-Xmx384m', '-cp', os.pathsep.join([str(classes), cp]),
                             'StrategySourceContractAuditCli', str(manifest)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
    (args.output_dir / 'audit.stdout.log').write_text(result.stdout, encoding='utf-8')
    (args.output_dir / 'audit.stderr.log').write_text(result.stderr, encoding='utf-8')
    result.check_returncode()
    records = []
    for line in result.stdout.splitlines():
        fields = line.split('\t')
        records.append({'hypothesis': fields[0], 'passed': fields[1] == 'PASS',
            'compile_log': '' if fields[1] == 'PASS' else base64.b64decode(fields[2]).decode('utf-8')})
    if len(records) != len(rows):
        raise ValueError('incomplete source diagnostic audit')
    source_validator = args.indsvr_repo / 'target/classes/com/app/dc/service/strategy/generate/StrategyGeneratedSourceValidator.class'
    atomic_write_json(args.output_dir / 'audit.json', {'candidates': len(records),
        'passed': sum(row['passed'] for row in records), 'records': records,
        'validator_class_sha256': hashlib.sha256(source_validator.read_bytes()).hexdigest(),
        'diagnostics_only': True, 'replaces_compilation_or_parity': False,
        'financial_data_read': False, 'production_write': False, 'server_or_llm_calls': 0})
    print('SOURCE_RULE_AUDIT', len(records), 'pass', sum(row['passed'] for row in records), flush=True)
    for record in records:
        if not record['passed']:
            print(record['hypothesis'], record['compile_log'].strip(), flush=True)


if __name__ == '__main__':
    main()
