"""Complete-proof-only training resolver. No controller handoff, server calls or financial bypass."""
from pathlib import Path

from recovery import cusum_training_proof_admission as admission
from recovery.verify_cusum_identity_matrix import digest_json, group_scopes
from recovery.verify_fit_only_risk_contract import sha


def require_receipt(proof, row, source, seed, artifact, signals):
    receipt = proof['training_proof_receipt']
    digest_fields = ('matrix_sha256', 'group_marker_sha256', 'scope_proof_sha256',
        'actual_canonical_full_year_log_sha256')
    if any(not isinstance(receipt.get(k), str) or len(receipt[k]) != 64
            or any(c not in '0123456789abcdef' for c in receipt[k]) for k in digest_fields):
        raise ValueError('complete matrix/group/scope/reference receipt digests required')
    if (proof['training_proof_receipt_sha256'] != digest_json(receipt)
            or receipt.get('schema') != 'verified_cusum_training_consumption_v1'
            or receipt.get('matrix_manifest_sha256') != admission.MANIFEST_SHA256
            or receipt.get('context_sha256') != admission.CONTEXT_SHA256
            or any(receipt.get(k) != row[k] for k in ('strategy', 'symbol', 'scene', 'side'))
            or receipt.get('current_source_sha256') != sha(Path(source))
            or receipt.get('current_seed_sha256') != sha(Path(seed))
            or receipt.get('artifact_sha256') != sha(Path(artifact))
            or receipt.get('training_bars') != 35040 or receipt.get('training_signals') != signals
            or receipt.get('mismatches') != 0 or receipt.get('training_check_reuse_verified') is not True
            or receipt.get('training_evidence_mode') != 'actual_canonical_full_year_and_exact_source_full_class_identity'
            or receipt.get('financial_replay_performed') is not False or receipt.get('production_write') is not False):
        raise ValueError('exact complete training proof receipt changed or crossed scope/source/scene boundaries')
    return receipt


class VerifiedCusumTrainingResolver:
    """Construction fails until the entire externally pinned training matrix is verified."""

    def __init__(self, matrix_dir, expected_matrix_sha256, environment_args):
        self.root = Path(matrix_dir).resolve()
        self.matrix_sha256 = expected_matrix_sha256
        self.environment_args = environment_args
        self.startup_audit = admission.verify_complete_matrix(self.root, self.matrix_sha256, self.environment_args)

    def __call__(self, row, source, seed):
        manifest, matrix = admission.terminal_documents(self.root, self.matrix_sha256)
        admission.require_environment(manifest['context'], self.environment_args)
        records = {r['strategy']: r for r in matrix['scope_records']}
        if row['strategy'] not in records:
            raise ValueError('scope absent from the exact completed CUSUM matrix')
        record = records[row['strategy']]
        resolved = admission.require_exact_scope(record, row, source, seed)
        references = {(r['symbol'], r['side']): r for r in matrix['canonical_references']}
        key = (record['symbol'], record['side'])
        rows = dict(group_scopes(manifest['queue']))[key]
        group_records = [records[r['strategy']] for r in rows]
        canonical = references[key]
        admission.verify_group(self.root, rows, canonical, group_records,
            admission.MANIFEST_SHA256, admission.CONTEXT_SHA256)
        group = self.root / 'groups' / row['symbol'] / ('long' if row['side'] > 0 else 'short')
        receipt = dict(schema='verified_cusum_training_consumption_v1',
            matrix_manifest_sha256=admission.MANIFEST_SHA256, matrix_sha256=self.matrix_sha256,
            context_sha256=admission.CONTEXT_SHA256, group_marker_sha256=sha(group / 'GROUP_COMPLETE.json'),
            scope_proof_sha256=sha(group / (row['strategy'] + '.json')),
            strategy=row['strategy'], symbol=row['symbol'], scene=row['scene'], side=row['side'],
            current_source_sha256=sha(Path(source)), current_seed_sha256=sha(Path(seed)),
            artifact_sha256=resolved['artifact_sha256'], canonical_strategy=canonical['strategy'],
            actual_canonical_full_year_log_sha256=canonical['full_year_log_sha256'],
            training_bars=35040, training_signals=resolved['training_signals'], mismatches=0,
            training_evidence_mode='actual_canonical_full_year_and_exact_source_full_class_identity',
            training_check_reuse_verified=True, financial_replay_performed=False, production_write=False)
        admission.terminal_documents(self.root, self.matrix_sha256)
        admission.require_environment(manifest['context'], self.environment_args)
        # Rebind exactly the consumer's own bytes after the potentially lengthy checks.
        admission.require_exact_scope(record, row, source, seed)
        return dict(source_sha256=record['source_sha256'], artifact_path=resolved['artifact_path'],
            artifact_sha256=resolved['artifact_sha256'], entry_class=resolved['entry_class'],
            signals=resolved['training_signals'], training_proof_receipt=receipt,
            training_proof_receipt_sha256=digest_json(receipt))
