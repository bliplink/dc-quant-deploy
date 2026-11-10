"""Read-only admission of the complete frozen CUSUM TRAINING proof; no finance or runtime wiring."""
import hashlib
import os
from pathlib import Path
import shutil

from recovery.class_identity_equivalence import require_jar_identity_equivalence, require_source_identity_equivalence
from recovery.run_cusum_drift_batch import SCOPE_FIELDS
from recovery.run_directional_clock_batch import require_hashes
from recovery.run_true_adx_batch import read
from recovery.verify_cusum_identity_matrix import (
    classpath_classes, digest_json, group_scopes, parse_parity,
    require_matching_reference, require_matrix_coverage, verify_compiled_record,
)
from recovery.verify_fit_only_risk_contract import sha

MANIFEST_SHA256 = 'a074c787bacd4a61f605113303636f76c4ca42dcb4e5f6867ddd036ced908e02'
CONTEXT_SHA256 = '7ef5634ee42c5ee6d14c66bc4afe8a2b99b7494a490426dfa7856e75470a9864'


def require_false(document, names):
    if any(document.get(name) is not False for name in names):
        raise ValueError('training-only/no-runtime/no-production evidence required')


def terminal_documents(root, expected_matrix_sha256):
    """Check the terminal boundary BEFORE opening a potentially live matrix ledger."""
    root = Path(root).resolve()
    if ((root / 'FAILED.json').exists() or not (root / 'MATRIX_COMPLETE.json').is_file()
            or not (root / 'status.json').is_file()):
        raise ValueError('complete successful matrix required; never consume a partial/live matrix')
    marker, status = read(root / 'MATRIX_COMPLETE.json'), read(root / 'status.json')
    if (marker.get('manifest_sha256') != MANIFEST_SHA256 or marker.get('completed_groups') != 20
            or marker.get('completed_scopes') != 100 or status.get('state') != 'COMPLETE'
            or status.get('completed_groups') != 20 or status.get('completed_scopes') != 100
            or status.get('total_groups') != 20 or status.get('total_scopes') != 100):
        raise ValueError('authoritative terminal20/100 marker and status required')
    require_false(marker, ('runtime_reuse_enabled', 'runtime_admission_ready', 'production_write'))
    require_false(status, ('runtime_reuse_enabled', 'financial_validation_started', 'production_write'))
    if (not isinstance(expected_matrix_sha256, str) or len(expected_matrix_sha256) != 64
            or any(c not in '0123456789abcdef' for c in expected_matrix_sha256)):
        raise ValueError('externally pinned exact completed-matrix SHA256 required')
    if (sha(root / 'manifest.json') != MANIFEST_SHA256
            or marker.get('matrix_sha256') != expected_matrix_sha256
            or sha(root / 'matrix.json') != expected_matrix_sha256):
        raise ValueError('frozen matrix manifest/content digest changed')
    manifest, matrix = read(root / 'manifest.json'), read(root / 'matrix.json')
    if (manifest.get('schema') != 'cusum_complete_training_identity_matrix_v1'
            or manifest.get('canonical_groups') != 20 or manifest.get('scope_proofs') != 100
            or manifest.get('mechanism_groups') != 1
            or digest_json(manifest['context']) != CONTEXT_SHA256
            or matrix.get('manifest_sha256') != MANIFEST_SHA256 or matrix.get('context_sha256') != CONTEXT_SHA256
            or matrix.get('actual_full_year_replays') != 20
            or matrix.get('actual_source_validations') != 100 or matrix.get('actual_scope_compilations') != 100):
        raise ValueError('original complete source policy and actual20/100 evidence required')
    require_false(manifest, ('runtime_reuse_enabled', 'financial_validation_started', 'new_holdout_read', 'production_write'))
    require_false(matrix, ('runtime_reuse_enabled', 'runtime_admission_ready', 'financial_validation_started',
        'new_holdout_read', 'production_write'))
    require_matrix_coverage(manifest['queue'], matrix['canonical_references'], matrix['scope_records'], CONTEXT_SHA256)
    if marker.get('nonzero_reference_groups') != sum(r['training_signals'] > 0 for r in matrix['canonical_references']):
        raise ValueError('nonzero training coverage count changed; zero signals cannot become coverage')
    return manifest, matrix


def require_environment(context, args):
    """Byte membership, Java options and original executable selection must still match."""
    if digest_json(context) != CONTEXT_SHA256:
        raise ValueError('not the original frozen CUSUM training context')
    current_jars = {str(p) for directory in ('dependency', 'javalib')
        for p in (args.sim_repo / 'target' / directory).glob('*.jar')}
    if (current_jars != set(context['runtime_jar_sha256'])
            or classpath_classes(args) != context['classpath_class_sha256']):
        raise ValueError('complete actual classpath membership or bytecode changed')
    for command in ('java', 'javac', 'jar'):
        selected = shutil.which(command)
        if not selected or str(Path(selected).resolve()) not in context['critical_sha256']:
            raise ValueError('original Java executable selection changed')
    current_options = {key: hashlib.sha256(os.environ.get(key, '').encode()).hexdigest()
        for key in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS')}
    if current_options != context['java_option_environment_sha256']:
        raise ValueError('Java option environment changed')
    for name in ('critical_sha256', 'training_sha256', 'runtime_jar_sha256'):
        require_hashes(context[name])


def require_inside(root, path, subtree):
    resolved = Path(path).resolve()
    if not resolved.is_relative_to((root / subtree).resolve()):
        raise ValueError('source evidence escaped its frozen matrix artifact directory')


def verify_group(root, rows, canonical, records, manifest_sha256, context_sha256):
    """May audit an immutable completed GROUP, but does not admit a partial matrix."""
    root = Path(root).resolve()
    group = root / 'groups' / canonical['symbol'] / ('long' if canonical['side'] > 0 else 'short')
    marker = read(group / 'GROUP_COMPLETE.json')
    if (marker.get('matrix_manifest_sha256') != manifest_sha256 or marker.get('context_sha256') != context_sha256
            or marker.get('completed_scopes') != 5 or marker.get('actual_full_year_replays') != 1
            or marker.get('canonical_sha256') != sha(group / 'canonical.json')
            or read(group / 'canonical.json') != canonical
            or set(marker.get('scope_proof_sha256', {})) != {r['strategy'] for r in rows}
            or len(records) != 5 or {r['strategy'] for r in records} != {r['strategy'] for r in rows}):
        raise ValueError('immutable complete five-scene group/reference required')
    require_false(marker, ('runtime_reuse_enabled', 'production_write'))
    by_name = {r['strategy']: r for r in records}
    for row in rows:
        record = by_name[row['strategy']]
        if any(record[k] != row[k] for k in SCOPE_FIELDS):
            raise ValueError('immutable group scope descriptor changed')
        require_matching_reference(record, canonical)
    for record in [canonical] + records:
        for key, subtree in (('source_path', 'frozen'), ('seed_path', 'frozen'),
                ('artifact_path', 'artifacts'), ('validator_log_path', 'logs')):
            require_inside(root, record[key], subtree)
        verify_compiled_record(record)
    require_inside(root, canonical['full_year_log_path'], 'logs')
    log = Path(canonical['full_year_log_path'])
    if (sha(log) != canonical['full_year_log_sha256']
            or parse_parity(log.read_text(encoding='utf-8')) != canonical['training_signals']):
        raise ValueError('actual original full-year signal/risk replay changed')
    for record in records:
        proof = group / (record['strategy'] + '.json')
        if sha(proof) != marker['scope_proof_sha256'][record['strategy']] or read(proof) != record:
            raise ValueError('per-scope immutable source proof changed')
        require_false(record, ('runtime_reuse_enabled', 'financial_validation_started', 'production_write'))
        require_source_identity_equivalence(Path(canonical['source_path']).read_text(encoding='utf-8'), canonical['strategy'],
            Path(record['source_path']).read_text(encoding='utf-8'), record['strategy'])
        identity = require_jar_identity_equivalence(Path(canonical['artifact_path']), canonical['strategy'],
            Path(record['artifact_path']), record['strategy'])
        if identity != record['identity_proof'] or len(identity['normalized_class_sha256']) != 3:
            raise ValueError('complete three-class identity proof changed')


def verify_complete_matrix(root, expected_matrix_sha256, args):
    manifest, matrix = terminal_documents(root, expected_matrix_sha256)
    require_environment(manifest['context'], args)
    references = {(r['symbol'], r['side']): r for r in matrix['canonical_references']}
    by_name = {r['strategy']: r for r in matrix['scope_records']}
    for key, rows in group_scopes(manifest['queue']):
        verify_group(root, rows, references[key], [by_name[r['strategy']] for r in rows], MANIFEST_SHA256, CONTEXT_SHA256)
    # Recheck the immutable terminal boundary and full environment after artifact reads.
    terminal_documents(root, expected_matrix_sha256)
    require_environment(manifest['context'], args)
    return dict(manifest_sha256=MANIFEST_SHA256, matrix_sha256=expected_matrix_sha256, context_sha256=CONTEXT_SHA256,
        verified_training_scopes=100, verified_actual_full_year_references=20,
        runtime_reuse_enabled=False, financial_validation_started=False, production_write=False)


def require_exact_scope(record, row, source, seed):
    """A future caller must bind its own unchanged source AND complete scene seed, not a name."""
    require_false(record, ('runtime_reuse_enabled', 'financial_validation_started', 'production_write'))
    if (any(record[k] != row[k] for k in SCOPE_FIELDS)
            or record.get('context_sha256') != CONTEXT_SHA256 or record.get('training_bars') != 35040
            or record.get('mismatches') != 0 or type(record.get('training_signals')) is not int
            or record['training_signals'] < 0
            or sha(Path(source)) != record['source_sha256'] or sha(Path(seed)) != record['seed_sha256']):
        raise ValueError('exact current scope/source/scene seed required; no cross-scope reuse')
    verify_compiled_record(record)
    return dict(artifact_path=record['artifact_path'], artifact_sha256=record['artifact_sha256'],
        entry_class=record['entry_class'], training_bars=35040, training_signals=record['training_signals'],
        mismatches=0, runtime_reuse_enabled=False, financial_validation_started=False, production_write=False)
