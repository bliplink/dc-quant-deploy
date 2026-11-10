"""Offline source/parameter oracle using pre-validation OHLCV; never a financial screen."""

import argparse
import csv
import hashlib
import io
import json
import re
import subprocess
from pathlib import Path

from recovery import local_strategy_backtest as runner
from recovery.export_representative_candidate import export_candidate
from recovery.run_representative_formal_batch import research_parity_classpath
from recovery.strategy_recovery_common import atomic_write_json


# Structural code-path coverage, fixed before reading any fit-risk financial result.
FAMILIES = ('TrendPullbackHypothesis', 'AtrTrendBreakoutHypothesis',
            'MedianDeviationReversalHypothesis', 'RsiAtrEnvelopeReentryLongHypothesis',
            'LowVolumeAtrEnvelopeReentryLongHypothesis', 'SceneBreakoutRetestHoldHypothesis',
            'SceneControlledBreakoutHypothesis', 'SceneExhaustionMidpointTurnHypothesis')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log):
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=600)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('engineering contract failed; preserve ' + str(log))
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('indsvr-repo', 'sim-repo', 'training-input-dir', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    for name in ('indsvr_repo', 'sim_repo', 'training_input_dir', 'output_dir'):
        setattr(args, name, getattr(args, name).resolve())
    output = args.output_dir
    if (output / 'manifest.json').exists():
        raise ValueError('engineering attempt already frozen; preserve it and use a new directory')
    output.mkdir(parents=True, exist_ok=True)
    research = args.indsvr_repo / 'src/test/java/com/app/dc/service/strategy/research/StrategyResearchBatchCli.java'
    class_dir = args.indsvr_repo / 'target/test-classes/com/app/dc/service/strategy/research'
    bars = args.training_input_dir / 'BTCUSDT-15m.tsv'
    ready = args.training_input_dir / 'READY.json'
    manifest = {'schema': 'fit_risk_engineering_contract_v1', 'market_begin': '2023-01-01',
                'market_end_inclusive': '2023-12-31', 'symbol': 'BTCUSDT',
                'families': FAMILIES, 'risk_profiles': [0, 1, 2, 3],
                'research_source_sha256': sha(research), 'bars_sha256': sha(bars),
                'ready_sha256': sha(ready), 'exporter_sha256': sha(Path(__file__).with_name('export_representative_candidate.py')),
                'research_class_sha256': {path.name: sha(path) for path in sorted(class_dir.glob('*.class'))},
                'actual_sim_class_sha256': {name: sha(args.sim_repo / 'target/classes' / name) for name in (
                    'com/app/dc/service/simulation/BacktestOptimizationService.class',
                    'com/app/dc/service/simulation/runtime/SliceOptimizedWalkForwardRunner.class')},
                'financial_validation_started': False, 'forward_pnl_read': False,
                'production_write': False, 'server_codegen_allowed': False}
    atomic_write_json(output / 'manifest.json', manifest)
    records = []
    try:
        catalog_text = execute(['java', '-Ddc.research.listRepresentativesOnly=true',
            '-Ddc.research.cohort=fit_only_risk_v1', '-cp', str(args.indsvr_repo / 'target/test-classes'),
            'com.app.dc.service.strategy.research.StrategyRepresentativeCatalogCli'], output / 'catalog.log')
        catalog = list(csv.DictReader(io.StringIO(catalog_text), delimiter='\t'))
        if len(catalog) != 400 or len({row['family'] for row in catalog}) != 202:
            raise ValueError('unexpected four-profile research catalog')
        campaign = output / 'campaign'
        campaign.mkdir()
        atomic_write_json(campaign / 'campaign.json', {'catalog': catalog,
            'source_sha256': {'StrategyResearchBatchCli': sha(research)},
            'financial_screen': False, 'production_write': False})
        cp = research_parity_classpath(args.indsvr_repo, args.sim_repo)
        for family in FAMILIES:
            row = next(item for item in catalog if item['family'] == 'FitOnlyRisk' + family)
            frozen, name = export_candidate(campaign, args.indsvr_repo, output / 'frozen',
                                             'BTCUSDT', 'trend', row['hypothesis'])
            artifact, entry_class, _ = runner.compile_source((frozen / 'GeneratedStrategy.java').read_text(encoding='utf-8'),
                args.sim_repo, output / 'artifacts' / family)
            execute(['java', '-Xmx256m', '-cp', cp,
                'com.app.dc.service.strategy.research.RepresentativeSignalParityCli', '--validate-source',
                str(frozen / 'GeneratedStrategy.java'), row['family'], name], output / 'logs' / family / 'source.log')
            for profile in range(4):
                text = execute(['java', '-Xmx384m', '-Duser.timezone=UTC', '-cp', cp,
                    'com.app.dc.service.strategy.research.RepresentativeSignalParityCli', str(bars),
                    'BTCUSDT', '2023-01-01', '2023-12-31', row['hypothesis'], str(artifact), entry_class,
                    str(profile)], output / 'logs' / family / ('profile-%d.log' % profile))
                counts = re.search(r'bars=(\d+), researchSignals=(\d+), exportedSignals=(\d+), mismatches=(\d+)', text)
                if not counts or int(counts[2]) <= 0 or counts[2] != counts[3] or int(counts[4]) != 0:
                    raise ValueError('profile parity requires actual matching signal coverage: ' + family)
                record = {'family': family, 'profile': profile, 'bars': int(counts[1]),
                          'signals': int(counts[2]), 'mismatches': 0,
                          'source_sha256': sha(frozen / 'GeneratedStrategy.java')}
                records.append(record)
                atomic_write_json(output / 'parity.json', records)
                print('RISK_PROFILE_PARITY', family, profile, 'signals', counts[2], flush=True)
            if family == FAMILIES[0]:
                request = json.loads((frozen / 'seed.json').read_text(encoding='utf-8'))['strategies'][0]['request']
                parameter_file = output / 'parameters.json'
                atomic_write_json(parameter_file, runner.build_parameters(request))
                oracle = execute(['java', '-Xmx256m', '-cp', cp,
                    'com.app.dc.service.strategy.research.FormalRiskParameterOracleCli', str(parameter_file)],
                    output / 'actual-optimizer-oracle.log')
                if len(re.findall(r'RISK_PARAMETER_ORACLE .* passed=true', oracle)) != 8:
                    raise ValueError('actual optimizer did not prove all eight engineering cases')
        atomic_write_json(output / 'audit.json', {'state': 'complete', 'source_contracts': len(FAMILIES),
            'profile_signal_parity_cases': len(records), 'actual_optimizer_cases': 8,
            'manifest_sha256': sha(output / 'manifest.json'), 'financial_validation_started': False,
            'forward_pnl_read': False, 'production_write': False})
    except Exception as error:
        atomic_write_json(output / 'audit.json', {'state': 'failed', 'error': str(error),
            'completed_profile_cases': len(records), 'financial_validation_started': False, 'production_write': False})
        raise


if __name__ == '__main__':
    main()
