#!/usr/bin/env python3
"""Measure fixed-rate signed Demo orders through authenticated execution push."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import sys
from threading import Event, Lock, Thread
import time


HERE = Path(__file__).resolve().parent
CANCEL = runpy.run_path(str(HERE / 'verify-mac-demo-order-cancel-capacity.py'))
CAPACITY, MEASURE = CANCEL['CAPACITY'], CANCEL['MEASURE']
SYMBOL, QUANTITY, PRICE = 'BTC004USDT', Decimal('0.001'), '90010'


def execution_reports(payload):
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return []
    if isinstance(payload, list):
        return [report for item in payload for report in execution_reports(item)]
    if isinstance(payload, dict) and payload.get('ExecType') == 'Trade' and payload.get('ExecID'):
        return [payload]
    return []


def signed_trader(location, run, index, accounts):
    from opentradingcore import OpenTradingCoreClient
    trader = CANCEL['new_trader'](location, SYMBOL, 'TRADE', run, index)
    issued = CANCEL['api']('LoginSvr', 'updateApiKey', {
        'cid': 'EXEC_KEY_' + run + str(index), 'label': 'execution-capacity-' + run,
        'type': 'trade'}, trader[2])
    # Keep credentials only in this process, never in reports or console output.
    account = {'trader': trader, 'key': issued['api_key'], 'client': None, 'order_attempted': False}
    accounts.append(account)
    client = OpenTradingCoreClient.from_api_key(
        base_url=CANCEL['URL'].rsplit('/httpapi/', 1)[0], location=location,
        api_key=issued['api_key'], api_secret=issued['secret_key'], timeout=8)
    account['client'] = client
    session = client.login(mode='trader')
    if session.user_id != trader[1] or session.client_type != 'API':
        raise RuntimeError('Signed benchmark identity mismatch')
    return client


def summary_ms(records, field):
    values = sorted(row[field] for row in records if field in row)
    return {'samples': len(values), **{label: MEASURE['percentile'](values, fraction)
            for label, fraction in [('p50', .5), ('p95', .95), ('p99', .99), ('p99_9', .999)]}}


def error_status(error):
    code = re.search(r'code=([A-Za-z0-9_-]+)', str(error))
    return {'type': type(error).__name__, 'code': code[1] if code else None}


def run_window(root, rate, seconds, run, report):
    stop, changed = Event(), Event()
    guard = Lock()
    accounts, records, seen, stream_errors = [], {}, set(), []
    receiver = None
    admin_session = {}
    with CANCEL['controlled_products'](run, report, admin_session=admin_session) as (location, products):
        if ('TRADE', SYMBOL) not in products:
            raise RuntimeError('Expected the funded controlled-price product')
        report.update(location=location, symbol=SYMBOL, quantity=str(QUANTITY), price=PRICE)
        try:
            report['controlled_robot_stop'] = CANCEL['stop_trial_robot_after_bootstrap'](
                location, admin_session['token'])
            report['background_robots_at_admission'] = CAPACITY['demo_tenants']()
            report['stage'] = 'SIGNED_MAKER_LOGIN'
            maker = signed_trader(location, run, 0, accounts)
            report['stage'] = 'SIGNED_TAKER_LOGIN'
            taker = signed_trader(location, run, 1, accounts)
            websocket_port = CAPACITY['FRESH']['env_pairs'](root / 'demo.env')['GW_WEBSOCKET_PORT']
            report['stage'] = 'PRIVATE_STREAM_CONNECT'
            taker.connect_stream('private', gateway_base_url='http://127.0.0.1:' + websocket_port)
            report['stage'] = 'PRIVATE_STREAM_SUBSCRIBE'
            taker.subscribe_executions(SYMBOL)

            def receive():
                from websocket import WebSocketTimeoutException
                while not stop.is_set():
                    try:
                        for event in taker.events(channel='private'):
                            received = time.monotonic_ns()
                            if stop.is_set():
                                return
                            for execution in execution_reports(event['data']):
                                client_id = execution.get('ClOrdID')
                                with guard:
                                    row = records.get(client_id)
                                    if row is None or execution.get('OrdStatus') != 'Filled':
                                        continue
                                    if execution.get('Location') != location or Decimal(str(execution.get('LastQty', '0'))) != QUANTITY:
                                        stream_errors.append('EXECUTION_IDENTITY_OR_QUANTITY_MISMATCH')
                                        continue
                                    identity = (client_id, execution['ExecID'])
                                    if identity in seen or 'execution_id' in row:
                                        stream_errors.append('DUPLICATE_FINAL_EXECUTION')
                                        continue
                                    seen.add(identity)
                                    row.update(execution_id=execution['ExecID'],
                                               received_ns=received,
                                               client_fill_ms=round((received - row['started_ns']) / 1e6, 3),
                                               scheduled_fill_ms=round((received - row['scheduled_ns']) / 1e6, 3),
                                               settlement_durability=execution.get('TradeSettlementDurability'),
                                               settlement_rpo_risk=execution.get('TradeSettlementRpoRisk'))
                                changed.set()
                    except WebSocketTimeoutException:
                        continue
                    except Exception as error:
                        if not stop.is_set():
                            stream_errors.append(type(error).__name__)
                        return

            receiver = Thread(target=receive, name='demo-execution-push', daemon=True)
            receiver.start()
            planned = int(rate * seconds)
            maker_id = 'T554EXEC-' + run + '-MAKER'
            report['stage'] = 'MAKER_PLACEMENT'
            accounts[0]['order_attempted'] = True
            maker.place_limit_order(SYMBOL, 'SELL', str(QUANTITY * (planned + 1)), PRICE, clord_id=maker_id)
            maker_trader = (location, maker.session.user_id, maker.session.token)
            CANCEL['await_order'](maker_trader, SYMBOL, maker_id, True)
            control_before = CAPACITY['require_strict_demo'](root)
            report['control_generation_before'] = control_before
            report['from'] = datetime.now(timezone.utc).isoformat()
            report['stage'] = 'FIXED_RATE_WINDOW'
            accounts[1]['order_attempted'] = True
            report['offered_until'] = (datetime.fromisoformat(report['from'])
                                       + timedelta(seconds=seconds)).isoformat()
            begun = time.monotonic_ns()
            pending = set()
            dropped = 0

            def submit(client_id, scheduled):
                started = time.monotonic_ns()
                with guard:
                    records[client_id] = {'client_order_id': client_id, 'scheduled_ns': scheduled,
                                          'started_ns': started,
                                          'dispatch_delay_ms': round((started - scheduled) / 1e6, 3)}
                outcome = 'ACKNOWLEDGED'
                try:
                    taker.call('OrderSvr', 'placeOrder', {
                        'Location': location, 'UserID': taker.session.user_id, 'SecurityID': SYMBOL,
                        'MarketIndicator': '4', 'OCType': 'OPEN', 'Side': 'Buy', 'OrdType': 'Limit',
                        'TimeInForce': 'IOC', 'OrderQty': str(QUANTITY), 'Price': PRICE,
                        'ClOrdID': client_id, 'Terminal': 'API', 'AlgoName': 'cross', 'Demo': '0'},
                        routing_key=location + '\x1f4\x1f' + SYMBOL)
                except Exception as error:
                    outcome = type(error).__name__
                finished = time.monotonic_ns()
                with guard:
                    records[client_id].update(outcome=outcome, ack_ms=round((finished - started) / 1e6, 3))

            with MEASURE['sample_resources'](root.name) as samples, ThreadPoolExecutor(max_workers=16) as clients:
                for index in range(planned):
                    scheduled = begun + round(index / rate * 1e9)
                    time.sleep(max(0, (scheduled - time.monotonic_ns()) / 1e9))
                    completed = {future for future in pending if future.done()}
                    for future in completed:
                        future.result()
                    pending.difference_update(completed)
                    if len(pending) == 16 or time.monotonic_ns() >= begun + seconds * 1e9:
                        dropped += 1
                        continue
                    client_id = 'T554EXEC-' + run + '-' + str(index)
                    pending.add(clients.submit(submit, client_id, scheduled))
                for future in pending:
                    future.result()
                time.sleep(max(0, (begun + seconds * 1e9 - time.monotonic_ns()) / 1e9))
                report['until'] = datetime.now(timezone.utc).isoformat()
                report['load_duration_seconds'] = round((time.monotonic_ns() - begun) / 1e9, 6)
                report['resource_samples'] = samples
            # Drain a bounded tail separately from the fixed offered-load window.
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                with guard:
                    complete = len(seen) == len(records)
                if complete or stream_errors:
                    break
                changed.wait(.1)
                changed.clear()
            with guard:
                report['orders'] = [dict(row) for row in records.values()]
            report['fills_inside_offered_window'] = sum(
                row.get('received_ns', float('inf')) <= begun + seconds * 1e9
                for row in report['orders'])
            report.update(scheduler_drops=dropped, stream_errors=list(stream_errors),
                          planned_orders=planned, measurement_complete=True)
            report['control_generation_after'] = CAPACITY['require_strict_demo'](root, check_space=False)
            report['control_stable'] = report['control_generation_after'] == control_before
        finally:
            stop.set()
            for account in accounts:
                client, trader = account['client'], account['trader']
                if client is not None:
                    try:
                        client.close_stream(channel='private')
                    except Exception as error:
                        report.setdefault('cleanup_errors', []).append(error_status(error))
                    if account['order_attempted']:
                        try:
                            scoped_trader = (location, trader[1], client.session.token)
                            for order in CANCEL['open_orders'](scoped_trader, SYMBOL):
                                client_id = order.get('ClOrdID') or order.get('ClOrderID')
                                if not client_id or not client_id.startswith('T554EXEC-' + run + '-'):
                                    raise RuntimeError('Unexpected order outside this benchmark run')
                                client.cancel_order(SYMBOL, order['OrderID'],
                                                    clord_id=client_id + '-CANCEL')
                                CANCEL['await_order'](scoped_trader, SYMBOL, client_id, False)
                            if CANCEL['open_orders'](scoped_trader, SYMBOL):
                                report.setdefault('cleanup_errors', []).append('REMAINING_OWN_ORDERS')
                        except Exception as error:
                            report.setdefault('cleanup_errors', []).append(error_status(error))
                try:
                    removed = CANCEL['PRODUCT']['call'](CANCEL['URL'], 'LoginSvr', 'deleteApiKey', {
                        'cid': 'EXEC_KEY_DELETE_' + run, 'api_key': account['key']}, trader[2])
                    if removed.get('code') != 0:
                        report.setdefault('cleanup_errors', []).append('TRADER_KEY_REVOKE_UNCONFIRMED')
                except Exception as error:
                    report.setdefault('cleanup_errors', []).append(error_status(error))
            if receiver is not None:
                receiver.join(timeout=5)
            if records and 'orders' not in report:
                with guard:
                    report['orders'] = [dict(row) for row in records.values()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('generation', type=Path)
    parser.add_argument('--rate', type=float, default=1)
    parser.add_argument('--seconds', type=int, default=60)
    args = parser.parse_args()
    if not 0 < args.rate <= 10 or not 60 <= args.seconds <= 300 or args.rate * args.seconds > 900:
        parser.error('Use 0–10 orders/s, 60–300 seconds, at most 900 planned orders')
    os.umask(0o077)
    root = args.generation.resolve(strict=True)
    sdk = Path(os.environ.get('MAC_DEMO_SDK_ROOT', str(HERE.parent / '.work/fresh-fullflow-20261021/sdk019/deployed-install')))
    sys.path.insert(0, str(sdk))
    try:
        from websocket import WebSocketTimeoutException  # noqa: F401
    except ImportError:
        parser.error('Install the deployed SDK realtime extra before creating benchmark tenants')
    CAPACITY['require_strict_demo'](root)
    run = secrets.token_hex(4)
    output = root / ('execution-capacity-' + run + '.json')
    report = {'generation': root.name, 'common_release': CAPACITY['common_release_identity'](root),
              'measurement_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'scope': 'Single tenant/product hotspot, signed HTTP submission to authenticated WebSocket final execution receipt',
              'arrival_model': 'Fixed scheduled rate, at most 16 outstanding HTTP requests, no mutation retries',
              'target_orders_per_second': args.rate, 'target_seconds': args.seconds, 'passed': False}
    try:
        with (root.parent / '.mac-demo-fresh.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            run_window(root, args.rate, args.seconds, run, report)
            rows = report.get('orders', [])
            report['responses'] = dict(Counter(row.get('outcome', 'NO_RESPONSE') for row in rows))
            for field in ['ack_ms', 'client_fill_ms', 'scheduled_fill_ms', 'dispatch_delay_ms']:
                report[field] = summary_ms(rows, field)
            report['missing_final_client_ids'] = [row['client_order_id'] for row in rows if 'execution_id' not in row]
            expected = {row['client_order_id'] for row in rows}
            deadline = time.monotonic() + 30
            while True:
                projected = CANCEL['PRODUCT']['readonly_sql'](
                    'SELECT o.clord_id,o.ord_status,COUNT(e.exec_id),COALESCE(SUM(e.last_qty),0) '
                    'FROM dc_orders o LEFT JOIN dc_orders_execorders e '
                    'ON e.location=o.location AND e.order_id=o.order_id '
                    f"WHERE o.location='{report['location']}' AND o.clord_id LIKE 'T554EXEC-{run}-%' "
                    f"AND o.clord_id<>'T554EXEC-{run}-MAKER' GROUP BY o.clord_id,o.order_id,o.ord_status")
                consistent = (len(projected) == len(expected)
                              and {row[0] for row in projected} == expected
                              and all(row[1] == 'Filled' and int(row[2]) == 1
                                      and Decimal(row[3]) == QUANTITY for row in projected))
                if consistent or time.monotonic() >= deadline:
                    break
                time.sleep(.5)
            report['projection'] = {'consistent': consistent, 'rows': projected}
            financial_code, financial, checks = CAPACITY['reconcile_financial_cursor']()
            report.update(financial_cursor=financial, financial_cursor_checks=checks)
            report['passed'] = (report.get('measurement_complete') is True and report['control_stable']
                                and len(rows) == report['planned_orders'] and report['scheduler_drops'] == 0
                                and report['responses'] == {'ACKNOWLEDGED': len(rows)}
                                and not report['missing_final_client_ids'] and not report['stream_errors']
                                and not report.get('cleanup_errors') and consistent and financial_code == 0)
    except Exception as error:
        report['failure_type'] = type(error).__name__
        report['failure_status'] = error_status(error)
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        with output.open('x') as evidence:
            json.dump(report, evidence, indent=2)
            evidence.write('\n')
    print(('PASS' if report['passed'] else 'NO_GO') + ' ' + str(output), flush=True)
    if not report['passed']:
        sys.exit(2)


if __name__ == '__main__':
    main()
