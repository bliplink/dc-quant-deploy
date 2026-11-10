"""Submit frozen, locally qualified catalog sources through INDSvr's normal import flow.

The server recompiles and backtests the last complete 365-day window before its
publisher decides whether to activate. No live registry rows are written here.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import csv
from collections import Counter
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import paramiko

from recovery.local_strategy_backtest import DEFAULT_HOST, DEFAULT_USER, DEFAULT_KEY
from recovery.prod_gateway_tunnel import ForwardServer, ForwardHandler
from recovery.strategy_recovery_common import (
    call_gateway, object_value, CANDIDATE_IMPORT_TOPIC, CANDIDATE_STATUS_TOPIC, LIVE_LIST_TOPIC,
)
from recovery.strategy_inventory_snapshot import query
from recovery.run_local_historical_scene_campaign import write_json


def prior_submission(output_dir, name, request):
    """Use the durable request ledger; an unversioned status query may return no candidate."""
    matches = []
    for peer in output_dir.parent.glob('strategy-95-server-*'):
        if peer.resolve() == output_dir.resolve() or not peer.is_dir():
            continue
        folder = peer / name
        request_path, response_path = folder / 'request.json', folder / 'submission.json'
        if not request_path.exists() or not response_path.exists():
            continue
        if json.loads(request_path.read_text(encoding='utf-8')) == request:
            response = json.loads(response_path.read_text(encoding='utf-8'))
            version = str(response.get('strategyVersion') or 'v1')
            order = int(version[1:]) if version.startswith('v') and version[1:].isdigit() else 0
            matches.append((order, response))
    return max(matches, key=lambda item: item[0])[1] if matches else None


def promotion_request(record, formal_dir, end_date):
    envelope = json.loads(Path(record['result_path']).read_text(encoding='utf-8'))
    result = envelope['result']
    if (not record['qualified'] or not result['qualified']
            or result.get('executionModelVersion') != 'v4_non_overlapping_walk_forward'
            or (result.get('holdout') or {}).get('passed') is not True
            or envelope.get('productionWrite') is not False):
        raise ValueError('candidate has no complete local formal and holdout qualification')
    source = Path(envelope['sourceFile']).read_text(encoding='utf-8')
    source_hash = hashlib.sha256(source.encode('utf-8')).hexdigest()
    if source_hash != record['source_sha256']:
        raise ValueError('frozen candidate source changed')
    # INDSvr's established source validator requires these exact argument names.
    # This is an identifier-only transform; retain the original local source hash.
    source = re.sub(r'\bkline\b', 'newKline', source)
    source = re.sub(r'\bindicators\b', 'indicatorSymbol', source)
    seed = json.loads((formal_dir / 'frozen' / record['strategy'] / 'seed.json').read_text(encoding='utf-8'))
    item = seed['strategies'][0]
    if (item['symbol'] != record['symbol'] or item['scene'] != record['scene']
            or item['strategyName'] != record['strategy']):
        raise ValueError('frozen strategy scope changed')
    request = dict(item['request'])
    request.update(strategyName=record['strategy'], scene=record['scene'],
                   symbol=record['symbol'], symbols=record['symbol'], text='15m',
                   description='Frozen catalog signal ' + record['hypothesis'] + '; ' + record['family'],
                   developmentMode='IMPORT', sync=False, validationOnly=False,
                   sourceRef='local-catalog-qualified:20261110:' + source_hash,
                   javaSourceBase64=base64.b64encode(source.encode('utf-8')).decode('ascii'))
    profile = dict(request['optimizationProfile'])
    profile['backtestEndDate'] = end_date.isoformat()
    profile['backtestBeginDate'] = (end_date - timedelta(days=364)).isoformat()
    request['optimizationProfile'] = profile
    return request


def source_only_execution_audit(status, request, llm_call_count):
    """Reject any server-side generator/repair fallback for uploaded source."""
    task = object_value(status.get('generationTask'))
    payload = object_value(task.get('payload'))
    expected = {'provider': 'external', 'sourceType': 'EXTERNAL_SOURCE',
                'generationType': 'EXTERNAL_IMPORT', 'generationEngine': 'external_java',
                'generationEngineRequested': 'external_java'}
    if any(payload.get(name) != value for name, value in expected.items()):
        raise ValueError('server did not execute the explicit external-source import contract')
    if payload.get('generationEngineFallback') not in (None, '') or llm_call_count != 0:
        raise ValueError('server import used a generator fallback or recorded LLM calls')
    source = base64.b64decode(request['javaSourceBase64'], validate=True)
    return {**expected, 'llm_call_count': 0, 'server_codegen_used': False,
            'uploaded_source_sha256': hashlib.sha256(source).hexdigest(),
            'uploaded_source_bytes': len(source)}


def reviewed_independent_candidates(records, document, active_rows):
    """Source-bound mechanism review is distinct from financial qualification."""
    reviews = document.get('reviews', []) if document.get('schema') == 'independent_mechanism_review_v1' else []
    by_name = {}
    for review in reviews:
        name = review.get('strategy')
        if not name or name in by_name:
            raise ValueError('missing or duplicate semantic review identity')
        by_name[name] = review
    approved, deferred, used = [], [], set()
    for record in records:
        review = by_name.get(record['strategy'], {})
        peers = sorted(row['strategy_name'] + '@' + row['strategy_version'] for row in active_rows
                       if row.get('reason') == 'qualified' and row['symbol_scope'] == record['symbol']
                       and row['scene'] == record['scene'])
        reason = None
        if review.get('decision') != 'APPROVE':
            reason = 'independent mechanism review absent or not approved'
        elif any(review.get(key) != record[key] for key in ('source_sha256', 'symbol', 'scene')):
            reason = 'semantic review source or scope changed'
        elif (not review.get('reviewer') or len(str(review.get('rationale') or '').strip()) < 20
              or not re.fullmatch(r'[a-z0-9_:-]{3,100}', str(review.get('mechanism_id') or ''))):
            reason = 'review requires an explicit mechanism, reviewer and substantive rationale'
        elif sorted(review.get('active_peers', [])) != peers:
            reason = 'review does not cover current qualified peers in the same cell'
        elif peers and any(len(str(review.get('peer_comparisons', {}).get(peer) or '').strip()) < 20 for peer in peers):
            reason = 'review lacks a substantive comparison against each active peer'
        key = record['symbol'], record['scene'], review.get('mechanism_id')
        if reason is None and key in used:
            reason = 'another candidate in the same cell uses the same reviewed mechanism'
        if reason:
            deferred.append({'strategy': record['strategy'], 'source_sha256': record['source_sha256'], 'reason': reason})
        else:
            approved.append(record)
            used.add(key)
    return approved, deferred


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--formal-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--backtest-end-date', type=date.fromisoformat, required=True)
    parser.add_argument('--limit', type=int, default=1)
    parser.add_argument('--wait-seconds', type=int, default=1800)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--require-semantic-review', action='store_true',
                        help='Also require source-bound independent-mechanism review for older cohorts')
    parser.add_argument('--semantic-review', type=Path,
                        help='Defaults to formal-dir/semantic-review.json; mandatory for CatalogAtrExit sources')
    parser.add_argument('--validator-classes',
                        help='Classpath containing the frozen source validator and parity CLI')
    parser.add_argument('--inventory-snapshot', type=Path,
                        help='Current qualification TSV; cap submissions at the remaining two-per-cell slots')
    parser.add_argument('--retry-source-format', action='store_true',
                        help='Retry only a failed exact-signature/IndicatorSymbol source validation')
    args = parser.parse_args()
    records = json.loads((args.formal_dir / 'results.json').read_text(encoding='utf-8'))
    qualified = sorted((record for record in records if record['qualified']),
                       key=lambda item: (item['symbol'], item['scene'],
                                         -item.get('validation_net_bps', 0), item['strategy']))
    occupied, occupied_names, active_rows = Counter(), set(), []
    if args.inventory_snapshot:
        with args.inventory_snapshot.open(encoding='utf-8', newline='') as stream:
            for row in csv.DictReader(stream, delimiter='\t'):
                active_rows.append(row)
                if row['reason'] == 'qualified':
                    occupied[row['symbol_scope'], row['scene']] += 1
                    occupied_names.add(row['strategy_name'])
    if args.limit > 0:
        qualified = qualified[:args.limit]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if qualified and (args.require_semantic_review or any(
            record['family'].startswith(('CatalogAtrExit', 'FitOnlyRisk')) for record in qualified)):
        review_path = args.semantic_review or args.formal_dir / 'semantic-review.json'
        document = json.loads(review_path.read_text(encoding='utf-8')) if review_path.exists() else {}
        if args.inventory_snapshot is None:
            raise ValueError('semantic release review requires a current inventory snapshot')
        qualified, deferred = reviewed_independent_candidates(qualified, document, active_rows)
        write_json(args.output_dir / 'semantic-review-audit.json', {
            'approved': [record['strategy'] for record in qualified], 'deferred': deferred,
            'review_file': str(review_path), 'production_write': False})
        print('semantic release review approved', len(qualified), 'deferred', len(deferred), flush=True)
    requests = []
    for record in qualified:
        request = promotion_request(record, args.formal_dir, args.backtest_end_date)
        destination = args.output_dir / record['strategy']
        destination.mkdir(parents=True, exist_ok=True)
        request_path = destination / 'request.json'
        if request_path.exists() and json.loads(request_path.read_text(encoding='utf-8')) != request:
            raise ValueError('server request changed after freeze')
        write_json(request_path, request)
        source_path = destination / 'GeneratedStrategy.java'
        source_path.write_text(base64.b64decode(request['javaSourceBase64']).decode('utf-8'),
                               encoding='utf-8', newline='\n')
        if args.validator_classes:
            validation = subprocess.run(['java', '-cp', args.validator_classes,
                'com.app.dc.service.strategy.research.RepresentativeSignalParityCli',
                '--validate-source', str(source_path), request['description'], request['strategyName']],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
            (destination / 'source-validation.log').write_text(
                validation.stdout + validation.stderr, encoding='utf-8')
            if validation.returncode:
                raise ValueError('server source contract validation failed: ' + str(destination))
        requests.append((record, request, destination))
    print('prepared locally qualified server candidates', len(requests), flush=True)
    if args.prepare_only or not requests:
        return
    if not args.validator_classes:
        parser.error('--validator-classes is required before server submission')
    client = paramiko.SSHClient()
    client.load_host_keys(str(Path.home() / '.ssh' / 'known_hosts'))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(DEFAULT_HOST, username=DEFAULT_USER, key_filename=DEFAULT_KEY,
                   passphrase=os.environ.pop('STC_PROD_KEY_PASSPHRASE'),
                   look_for_keys=False, allow_agent=False, timeout=20)
    client.get_transport().set_keepalive(20)
    server = None
    try:
        ForwardHandler.transport = client.get_transport()
        ForwardHandler.remote_port = 31002
        server = ForwardServer(('127.0.0.1', 0), ForwardHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = 'http://127.0.0.1:%d/gw' % server.server_address[1]
        api_key = os.environ.get('DC_GW_APIKEY', '1')
        # Harmless read proves this is the quant GW, rather than the retained legacy port 3002.
        call_gateway(url, api_key, LIVE_LIST_TOPIC, {'status': 'ACTIVE', 'pageSize': 1}, attempts=1)
        for record, request, destination in requests:
            name = record['strategy']
            cell = record['symbol'], record['scene']
            if occupied[cell] >= 2:
                print(name, 'skip: symbol/scene already has two qualified entries', flush=True)
                continue
            response_path = destination / 'submission.json'
            if response_path.exists():
                response = json.loads(response_path.read_text(encoding='utf-8'))
            else:
                prior = prior_submission(args.output_dir, name, request)
                if prior is not None:
                    write_json(response_path, prior)
                    print(name, 'reusing durable server submission', prior.get('strategyVersion'), flush=True)
                    response = prior
                else:
                    response = None
            if not response_path.exists():
                existing = call_gateway(url, api_key, CANDIDATE_STATUS_TOPIC,
                                        {'strategyName': name, 'strategyVersion': 'v1'}, attempts=1)
                write_json(destination / 'before-status.json', existing)
                summary = existing.get('summary') or {}
                compile_log = str((existing.get('generationTask') or {}).get('compile_log') or '')
                format_failure = (args.retry_source_format
                                  and summary.get('generationStatus') == 'FAILED'
                                  and summary.get('generationFailureCode') == 'COMPILE_FAILED'
                                  and ('Method signature must be exactly:' in compile_log
                                       or 'must use indicatorSymbol.getIndicator(symbol)' in compile_log))
                if not format_failure and any(str(summary.get(key) or '-').upper() not in ('', '-')
                       for key in ('candidateStatus', 'generationStatus', 'backtestTaskStatus')):
                    existing_version = str((existing.get('candidate') or {}).get('strategy_version')
                                           or (existing.get('generationTask') or {}).get('strategy_version') or 'v1')
                    response = {'strategyName': name, 'strategyVersion': existing_version, 'existing': True}
                else:
                    write_json(destination / 'submission-attempt.json', {'strategy': name,
                               'request_sha256': hashlib.sha256((destination / 'request.json').read_bytes()).hexdigest()})
                    response = call_gateway(url, api_key, CANDIDATE_IMPORT_TOPIC, request,
                                            timeout=180, attempts=1)
                write_json(response_path, response)
            version = str(response.get('strategyVersion') or 'v1')
            print('server candidate', name, version, 'submitted', flush=True)
            deadline = time.monotonic() + args.wait_seconds
            previous = None
            while time.monotonic() < deadline:
                status = call_gateway(url, api_key, CANDIDATE_STATUS_TOPIC,
                                      {'strategyName': name, 'strategyVersion': version}, attempts=1)
                write_json(destination / 'status.json', status)
                summary = status.get('summary') or {}
                phases = (str(summary.get('generationStatus') or '-').upper(),
                          str(summary.get('backtestTaskStatus') or '-').upper())
                if phases != previous:
                    print(name, 'generation', phases[0], 'backtest', phases[1], flush=True)
                    previous = phases
                if phases[0] in ('FAILED', 'CANCELLED', 'SKIPPED') or phases[1] in (
                        'SUCCESS', 'FAILED', 'CANCELLED', 'SKIPPED', 'SUSPENDED'):
                    # Query only the exact imported version, not unrelated scene/selection LLM calls.
                    safe_name = name.replace("'", "''")
                    safe_version = version.replace("'", "''")
                    calls = query(client, "SELECT count() AS count FROM dc.strategy_llm_call_log "
                                  "WHERE strategy_name='" + safe_name + "' AND strategy_version='"
                                  + safe_version + "' FORMAT JSONEachRow")[0]['count']
                    write_json(destination / 'source-only-audit.json',
                               source_only_execution_audit(status, request, calls))
                    live = call_gateway(url, api_key, LIVE_LIST_TOPIC,
                                        {'strategyName': name, 'status': 'ACTIVE', 'pageSize': 20}, attempts=1)
                    write_json(destination / 'live.json', live)
                    active = [row for row in live.get('items', []) if row.get('strategyName') == name
                              and str(row.get('status')).upper() == 'ACTIVE'
                              and str(row.get('strategyVersion') or row.get('strategy_version')) == version]
                    write_json(destination / 'outcome.json', {'strategy': name, 'version': version,
                               'generation_status': phases[0], 'backtest_status': phases[1],
                               'published': bool(active), 'registry_versions': active})
                    print(name, 'server terminal', phases, 'published', bool(active), flush=True)
                    if active and name not in occupied_names:
                        occupied[cell] += 1
                        occupied_names.add(name)
                    break
                time.sleep(5)
            else:
                print(name, 'server still running; resume using saved submission', flush=True)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        client.close()


if __name__ == '__main__':
    main()
