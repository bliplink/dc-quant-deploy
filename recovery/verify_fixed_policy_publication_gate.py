"""Observe actual unchanged optimization/publication classes with synthetic passing summaries, no market replay."""
import argparse
import json
import os
from pathlib import Path

from recovery.local_strategy_backtest import java_classpath
from recovery.strategy_recovery_common import atomic_write_json
from recovery.verify_fit_only_risk_contract import sha
from recovery.verify_ohlcv_profile_proxy import execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sim-repo', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(); sim = args.sim_repo.resolve(); output = args.output_dir.resolve()
    if output.exists(): raise ValueError('preserve all probe attempts; fresh output required')
    source = Path(__file__).with_name('java') / 'FixedPolicyPublicationGateProbe.java'
    classes = output / 'classes'; classes.mkdir(parents=True)
    paths = [sim / 'target/classes/com/app/dc/service/simulation/runtime/StrategyAutoPublishService.class',
             sim / 'target/classes/com/app/dc/service/simulation/BacktestOptimizationService.class']
    manifest = dict(probe_source_sha256=sha(source), formal_class_sha256={str(p): sha(p) for p in paths},
                    synthetic_summary_only=True, financial_replay_performed=False, production_write=False)
    atomic_write_json(output / 'manifest.json', manifest)
    cp = str(classes) + os.pathsep + java_classpath(sim)
    try:
        execute(['javac', '-J-Xmx256m', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-cp', cp,
                 '-d', str(classes), str(source)], output / 'compile.log')
        text = execute(['java', '-Xmx256m', '-cp', cp, 'com.app.dc.service.simulation.FixedPolicyPublicationGateProbe'], output / 'probe.log')
        line = next(line for line in text.splitlines() if line.startswith('FIXED_POLICY_GATE_OBSERVATION='))
        result = json.loads(line.split('=', 1)[1]); atomic_write_json(output / 'observation.json', result)
        if any(sha(Path(p)) != digest for p, digest in manifest['formal_class_sha256'].items()):
            raise ValueError('unchanged formal classes changed during observation')
        atomic_write_json(output / 'PROBE_COMPLETE.json', dict(manifest_sha256=sha(output / 'manifest.json'),
            observation_sha256=sha(output / 'observation.json'), production_write=False, financial_replay_performed=False))
        print(json.dumps(result), flush=True)
    except Exception as error:
        atomic_write_json(output / 'FAILED.json', dict(error=str(error), production_write=False)); raise


if __name__ == '__main__': main()
