"""Train one frozen formal-payoff hypothesis, with no server/model API calls."""
import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('input-dir', 'parent-model-dir', 'oracle-audit', 'dataset-dir', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    subprocess.run([sys.executable, '-u', '-m', 'recovery.build_formal_payoff_event_dataset',
        '--input-dir', str(args.input_dir), '--parent-model-dir', str(args.parent_model_dir),
        '--oracle-audit', str(args.oracle_audit), '--output-dir', str(args.dataset_dir)], check=True)
    subprocess.run([sys.executable, '-u', '-m', 'recovery.train_structural_expectancy_models',
        '--dataset-dir', str(args.dataset_dir), '--output-dir', str(args.output_dir),
        '--formal-payoff-labels'], check=True)


if __name__ == '__main__':
    main()
