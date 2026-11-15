#!/usr/bin/env python3
"""Measure simultaneous native TCP execution streams on distinct certified partitions."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import runpy
import secrets
import signal
import sys
import time
import zlib

HERE = Path(__file__).resolve().parent
EXEC = runpy.run_path(str(HERE / 'verify-mac-demo-execution-capacity.py'))
CANCEL, CAPACITY, MEASURE = (EXEC[key] for key in ('CANCEL', 'CAPACITY', 'MEASURE'))
NATIVE = runpy.run_path(str(HERE / 'mac-demo-native-tcp.py'))
RPO = runpy.run_path(str(HERE / 'verify-mac-demo-async-rpo.py'))
PERFORMANCE = runpy.run_path(str(HERE / 'mac-demo-performance-target.py'))


def validate_offered_load(streams, rate, seconds):
    """Keep every ordinary authenticated session below the existing gateway quota.

    Sixteen independent sessions can offer 1,040/s at 65/s each; using
    eight sessions at 130/s would test admission rejection instead of capacity.
    The session cap includes headroom below the current 100 RPC/s profile.
    """
    if (streams not in (2, 4, 8, 16) or not math.isfinite(rate)
            or not 0 < rate <= 80 or not 60 <= seconds <= 120
            or rate * seconds > 10000):
        raise ValueError('Use 2/4/8/16 independent streams, at most 80 orders/s per session, '
                         '60–120 seconds and at most 10000 orders per funded stream')
    return {'sessions': streams, 'per_session_offered_requests_per_second': rate,
            'per_session_request_budget_per_second': 80,
            'gateway_profile_changed': False,
            'total_offered_executions_per_second': streams * rate}


def reviewed_replication_lanes(root):
    """Describe only the lane formula present in this release's verified source."""
    release = CAPACITY['FRESH']['env_pairs'](root / 'common-release.env')
    source = Path(release['common_fault_result']) / 'source/src/main/java/com/app/common/replication/DirectNettyReplicationTransport.java'
    try:
        raw = source.read_bytes()
    except OSError:
        return {'available': False}
    text = raw.decode('utf-8')
    match = re.search(r'PARTITION_REPLICATION_LANES\s*=\s*([1-9][0-9]*)\s*;', text)
    compact = re.sub(r'\s+', '', text)
    if (not match or not 1 <= int(match[1]) <= 64
            or 'Math.floorMod(batch.getPartitionId().hashCode(),PARTITION_REPLICATION_LANES)' not in compact
            or 'request.getPartitionId().hashCode(),PARTITION_REPLICATION_LANES' not in compact):
        return {'available': False}
    return {'available': True, 'count': int(match[1]), 'source_sha256': hashlib.sha256(raw).hexdigest(),
            'scope': 'Derived connection affinity from exact verified Common source; not a worker utilization measurement'}


def summarize_streams(streams, seconds, expected_policy=None):
    """Keep missing replies, duplicate fills, skew and tail completion visible."""
    if not streams or any(not isinstance(row.get('measurement'), dict) for row in streams):
        raise RuntimeError('Every admitted native stream requires its own complete report')
    for key in ('order_partition', 'trade_partition'):
        if len({row[key] for row in streams}) != len(streams):
            raise RuntimeError('Distributed load requires distinct ' + key)
    for key in ('order_primary', 'trade_primary'):
        if len({row[key] for row in streams}) != 2:
            raise RuntimeError('Distributed load must exercise both physical primaries for ' + key)
    rows = []
    starts = []
    count_inside = 0
    protocol = []
    complete = True
    planned = drops = 0
    for stream in streams:
        measured = stream['measurement']
        starts.append(datetime.fromisoformat(measured.get('actual_start', measured['from']).replace('Z', '+00:00')).timestamp())
        planned += measured['planned_orders']
        drops += measured['scheduler_drops']
        count_inside += measured['fills_inside_offered_window']
        protocol.extend(measured['stream_errors'])
        complete = complete and measured.get('measurement_complete') is True
        for row in measured['orders']:
            rows.append(dict(row, location=stream['location']))
    if expected_policy is not None:
        if expected_policy not in ('STRICT_QUORUM', 'LOCAL_DURABLE_ASYNC'):
            raise RuntimeError('Unsupported measured client durability policy')
        asynchronous = expected_policy == 'LOCAL_DURABLE_ASYNC'
        durability = 'LOCAL_DURABLE_ASYNC' if asynchronous else 'QUORUM_DURABLE'
        if any(row.get('execution_id') and (row.get('settlement_durability') != durability
               or row.get('settlement_rpo_risk') is not asynchronous) for row in rows):
            protocol.append('SETTLEMENT_DURABILITY_POLICY_MISMATCH')
    fills = [row['execution_id'] for row in rows if row.get('execution_id')]
    if len(fills) != len(set(fills)):
        protocol.append('DUPLICATE_FINAL_EXECUTION_ACROSS_STREAMS')
    identities = [(row['location'], row['client_order_id']) for row in rows]
    if len(identities) != len(set(identities)):
        protocol.append('DUPLICATE_CLIENT_REQUEST_ACROSS_STREAMS')
    spread = 1000 * (max(starts) - min(starts))
    responses = dict(Counter(row.get('outcome', 'NO_RESPONSE') for row in rows))
    accounted = len(rows) + drops == planned
    semantic_pass = (complete and spread <= 250 and accounted and len(rows) > 0
                     and responses == {'ACKNOWLEDGED': len(rows)} and len(fills) == len(rows) and not protocol)
    result = {'planned_orders': planned, 'sent_orders': len(rows), 'final_executions': len(fills),
              'fills_inside_offered_window': count_inside, 'scheduler_drops': drops,
              'responses': responses, 'stream_errors': protocol, 'start_spread_ms': round(spread, 3),
              'generator_accounting_pass': accounted,
              'observed_window_execution_rate': count_inside / seconds,
              'window_delivery_fraction': count_inside / planned if planned else 0,
              'all_accepted_final_receipts_pass': semantic_pass,
              'window_capacity_pass': semantic_pass and drops == 0 and count_inside == planned}
    for field in ('ack_ms', 'client_fill_ms', 'scheduled_fill_ms', 'dispatch_delay_ms'):
        result[field] = EXEC['summary_ms'](rows, field)
    return result


def projected_stream(stream):
    expected = {row['client_order_id'] for row in stream['measurement']['orders']}
    run = stream['run']
    rows = CANCEL['PRODUCT']['readonly_sql'](
        'SELECT o.clord_id,o.ord_status,COUNT(e.exec_id),COALESCE(SUM(e.last_qty),0) '
        'FROM dc_orders o LEFT JOIN dc_orders_execorders e '
        'ON e.location=o.location AND e.order_id=o.order_id '
        f"WHERE o.location='{stream['location']}' AND o.clord_id LIKE 'T554EXEC-{run}-%' "
        f"AND o.clord_id<>'T554EXEC-{run}-MAKER' GROUP BY o.clord_id,o.order_id,o.ord_status")
    return {'rows': len(rows), 'expected_rows': len(expected), 'consistent':
            len(rows) == len(expected) and {row[0] for row in rows} == expected
            and all(row[1] == 'Filled' and int(row[2]) == 1
                    and Decimal(row[3]) == EXEC['QUANTITY'] for row in rows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('generation', type=Path)
    parser.add_argument('--streams', type=int, choices=(2, 4, 8, 16), default=4)
    parser.add_argument('--rate-per-stream', type=float, default=1)
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--require-performance-target', action='store_true')
    parser.add_argument('--diagnostic-only', action='store_true',
                        help='Retain integrity results but exclude an observed/profiled window from performance acceptance')
    parser.add_argument('--diagnostic-jfr', action='store_true',
                        help='Record bounded JDK profiles; requires --diagnostic-only')
    args = parser.parse_args()
    if args.diagnostic_only and args.require_performance_target:
        parser.error('A diagnostic window cannot be used for performance acceptance')
    if args.diagnostic_jfr and not args.diagnostic_only:
        parser.error('JFR requires --diagnostic-only; profiled performance cannot pass acceptance')
    try:
        admission_budget = validate_offered_load(args.streams, args.rate_per_stream, args.seconds)
    except ValueError as error:
        parser.error(str(error))
    os.umask(0o077)
    root = args.generation.resolve(strict=True)
    sdk = Path(os.environ.get('MAC_DEMO_SDK_ROOT', str(
        HERE.parent / '.work/fresh-fullflow-20261021/sdk019/deployed-install')))
    sys.path.insert(0, str(sdk))
    run_id = secrets.token_hex(4)
    output = root / ('distributed-execution-capacity-' + run_id + '.json')
    report = {'passed': False, 'generation': root.name, 'transport': 'tcp',
              'stage': 'ADMISSION',
              'scope': 'Independent funded tenants, distinct Order and Trade partitions, both A/B primaries; original live Robot background',
              'target_streams': args.streams, 'target_orders_per_second': args.streams * args.rate_per_stream,
              'target_seconds': args.seconds, 'streams': [], 'excluded_setup': [],
              'diagnostic_only': args.diagnostic_only,
              'native_session_admission_budget': admission_budget,
              'measurement_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'native_wrapper_sha256': hashlib.sha256((HERE / 'mac-demo-native-tcp.py').read_bytes()).hexdigest(),
              'started_at': datetime.now(timezone.utc).isoformat()}
    try:
        with (root.parent / '.mac-demo-fresh.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = CAPACITY['require_strict_demo'](root)
            report['common_release'] = CAPACITY['common_release_identity'](root)
            report['reviewed_replication_lanes'] = reviewed_replication_lanes(root)
            baseline = CAPACITY['demo_tenants']()
            if len(baseline) != 10 or any(value != 'RUNNING' for value in baseline.values()):
                raise RuntimeError('Distributed measurement requires the original ten healthy Robots')
            report['background_robots_before'] = baseline
            report['background_settlement_admission'] = CAPACITY['require_robot_settlements_ready'](root)
            manifest = {kind: RPO['manifest'](root, kind) for kind in ('order', 'trade')}
            work = NATIVE['prepare'](root)
            report['native_client_artifact'] = str(work)
            report['native_client_identity'] = json.loads((work / 'identity.json').read_text())
            # Credentials remain in these local variables, never in report/config files or command lines.
            private = []
            with ExitStack() as setup:
                try:
                    report['stage'] = 'CONTROLLED_TENANT_AND_ACCOUNT_SETUP'
                    for attempt in range(args.streams + 12):
                        if len(private) == args.streams:
                            break
                        run = secrets.token_hex(4)
                        stream = {'run': run, 'setup_attempt': attempt}
                        candidate = setup.enter_context(ExitStack())
                        location, products = candidate.enter_context(CANCEL['controlled_products'](run, stream))
                        symbol = EXEC['SYMBOL']
                        if ('TRADE', symbol) not in products:
                            raise RuntimeError('Controlled funded Trade product is absent')
                        stream.update(location=location, symbol=symbol)
                        for kind, key in [('trade', location), ('order', location + '\x1f4\x1f' + symbol)]:
                            part = 'P%03d' % (zlib.crc32(key.encode()) % 256)
                            stream[kind + '_partition'] = part
                            stream[kind + '_primary'] = manifest[kind][part]['primary']
                            layout = report['reviewed_replication_lanes']
                            if layout['available']:
                                lane = 0
                                for character in part:
                                    lane = (31 * lane + ord(character)) % layout['count']
                                stream[kind + '_replication_lane'] = lane
                        used = report['streams']
                        collision = any(any(row[kind + '_partition'] == stream[kind + '_partition']
                                            for row in used) for kind in ('order', 'trade'))
                        unbalanced = len(private) == args.streams - 1 and any(
                            len({row[kind + '_primary'] for row in used} | {stream[kind + '_primary']}) != 2
                            for kind in ('order', 'trade'))
                        if collision or unbalanced:
                            report['excluded_setup'].append({'location': location,
                                'reason': 'PARTITION_COLLISION' if collision else 'PRIMARY_BALANCE'})
                            candidate.close()
                            continue
                        accounts = []
                        private.append((stream, accounts, None))
                        report['streams'].append(stream)
                        maker = EXEC['signed_trader'](location, run, 0, accounts)
                        taker = EXEC['signed_trader'](location, run, 1, accounts)
                        stream.update(maker_user_id=maker.session.user_id, taker_user_id=taker.session.user_id)
                        planned = int(args.rate_per_stream * args.seconds)
                        maker_id = 'T554EXEC-' + run + '-MAKER'
                        accounts[0]['order_attempted'] = True
                        maker.place_limit_order(symbol, 'SELL', str(EXEC['QUANTITY'] * (planned + 1)),
                                                EXEC['PRICE'], clord_id=maker_id)
                        CANCEL['await_order']((location, maker.session.user_id, maker.session.token),
                                              symbol, maker_id, True)
                        config = {'location': location, 'user_id': taker.session.user_id,
                                  'token': taker.session.token, 'symbol': symbol,
                                  'quantity': str(EXEC['QUANTITY']), 'price': EXEC['PRICE'],
                                  'port': int(CAPACITY['FRESH']['env_pairs'](root / 'demo.env')['GW_TCP_PORT']),
                                  'run': run, 'rate': args.rate_per_stream, 'seconds': args.seconds}
                        private[-1] = (stream, accounts, config)
                    if len(private) != args.streams:
                        raise RuntimeError('Bounded setup did not find balanced distinct partitions')
                    report['background_robots_at_admission'] = CAPACITY['demo_tenants']()
                    if report['background_robots_at_admission'] != baseline:
                        raise RuntimeError('Original Robot cohort changed during setup')
                    report['control_generation_before'] = CAPACITY['require_strict_demo'](root)
                    if report['control_generation_before'] != before:
                        raise RuntimeError('Common control changed before the offered window')
                    with ExitStack() as diagnostics:
                        if args.diagnostic_jfr:
                            diagnostics.enter_context(runpy.run_path(str(HERE / 'mac-demo-jfr.py'))['observe'](
                                root, args.seconds + 180, report))
                        start = int(time.time() * 1000) + 15000
                        report['scheduled_start_epoch_ms'] = start
                        report['stage'] = 'SYNCHRONIZED_NATIVE_TCP_WINDOW'
                        samples = diagnostics.enter_context(MEASURE['sample_resources'](root.name))
                        with ThreadPoolExecutor(max_workers=args.streams) as pool:
                            jobs = {}
                            for stream, accounts, config in private:
                                config['start_at_epoch_ms'] = start
                                accounts[1]['order_attempted'] = True
                                jobs[pool.submit(NATIVE['run'], work, config)] = stream
                            failures = []
                            for job in as_completed(jobs):
                                try:
                                    jobs[job]['measurement'] = job.result()
                                except Exception as error:
                                    failures.append(EXEC['error_status'](error))
                            if failures:
                                report['client_failures'] = failures
                                raise RuntimeError('One or more native streams failed; inspect bounded diagnostics')
                    report['resource_samples'] = samples
                    report['stage'] = 'CLIENT_AND_PROJECTION_VERIFICATION'
                    report['aggregate'] = summarize_streams(
                        report['streams'], args.seconds, report['common_release']['client_ack_policy'])
                    report['control_generation_after'] = CAPACITY['require_strict_demo'](root, check_space=False)
                    report['control_stable'] = report['control_generation_after'] == before
                    deadline = time.monotonic() + 45
                    while True:
                        for stream in report['streams']:
                            stream['projection'] = projected_stream(stream)
                        if all(s['projection']['consistent'] for s in report['streams']) or time.monotonic() >= deadline:
                            break
                        time.sleep(.5)
                finally:
                    if sys.exc_info()[0] is not None:
                        report['failure_stage'] = report['stage']
                    report['stage'] = 'NORMAL_ACCOUNT_CLEANUP'
                    for stream, accounts, config in private:
                        EXEC['cleanup_accounts'](accounts, stream['location'], stream['run'], stream,
                                                 refresh_credentials=True)
            report['stage'] = 'SOURCE_FINANCIAL_AND_ORIGINAL_ROBOT_VERIFICATION'
            code, financial, checks = CAPACITY['reconcile_financial_cursor']()
            report.update(financial_cursor=financial, financial_cursor_checks=checks)
            offered = datetime.fromtimestamp(report['scheduled_start_epoch_ms'] / 1000, timezone.utc)
            report['background_robot_window'] = MEASURE['measure'](
                root.name, offered, offered + timedelta(seconds=args.seconds), set(baseline))
            gaps = report['background_robot_window']['largest_tape_fill_gap_seconds_by_tenant']
            report['background_real_fills_all_tenants'] = (
                set(gaps) == set(baseline) and all(gap < args.seconds for gap in gaps.values()))
            report['background_tape_terminal_audit'] = CAPACITY['audit_tape_immediate_terminals'](baseline)
            report['background_robots_after'] = CAPACITY['demo_tenants']()
            report['passed'] = (report.get('aggregate', {}).get('all_accepted_final_receipts_pass') is True
                                and report['control_stable'] and code == 0
                                and report['background_robots_after'] == baseline
                                and report['background_real_fills_all_tenants']
                                and report['background_tape_terminal_audit']['passed']
                                and all(s['projection']['consistent'] and not s.get('cleanup_errors')
                                        and not s['price_source']['errors']
                                        for s in report['streams']))
            report['stage'] = 'COMPLETE'
    except BaseException as error:
        report['failure'] = EXEC['error_status'](error)
        report.setdefault('failure_stage', report['stage'])
    finally:
        report['phase_one_performance'] = PERFORMANCE['execution_target'](
            report.get('aggregate', {}), args.seconds, report['passed'],
            qualified_window=not args.diagnostic_only)
        report['performance_target_required'] = args.require_performance_target
        report['integrity_passed'] = report['passed']
        if args.require_performance_target:
            report['passed'] = report['passed'] and report['phase_one_performance']['passed']
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        with output.open('x') as evidence:
            json.dump(report, evidence, indent=2)
            evidence.write('\n')
    prefix = 'DIAGNOSTIC_INTEGRITY_PASS' if args.diagnostic_only and report['passed'] else 'PASS' if report['passed'] else 'NO_GO'
    print(prefix + ' ' + str(output), flush=True)
    return 0 if report['passed'] else 2


if __name__ == '__main__':
    def terminate(signum, frame):
        raise KeyboardInterrupt('Bounded distributed measurement termination')
    signal.signal(signal.SIGTERM, terminate)
    sys.exit(main())
