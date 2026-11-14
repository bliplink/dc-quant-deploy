#!/usr/bin/env python3
"""Exercise real multi-maker orders and financial/public projections on the active Mac Demo."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import runpy
import secrets
import sys
from threading import Event, Lock, Thread
import time
import traceback

HERE = Path(__file__).resolve().parent
CANCEL = runpy.run_path(str(HERE / 'verify-mac-demo-order-cancel-capacity.py'))
CAPACITY, PRODUCT = CANCEL['CAPACITY'], CANCEL['PRODUCT']
D = Decimal
CASES = [('IOC_FULL', 'IOC', '.0004', '.0004', 'Filled'),
         ('FOK_FULL', 'FOK', '.0004', '.0004', 'Filled'),
         ('FOK_INSUFFICIENT', 'FOK', '.0008', '0', 'Cancelled'),
         ('IOC_PARTIAL', 'IOC', '.0008', '.0006', 'Cancelled'),
         ('GTC_PARTIAL', 'GTC', '.0008', '.0006', 'Partially_Filled'),
         ('PO_CROSS', 'PO', '.0004', '0', 'Cancelled')]


def wait(check, message, seconds=60):
    deadline = time.monotonic() + seconds
    while True:
        value = check()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise RuntimeError(message)
        time.sleep(.1)


def reports(data):
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return []
    if isinstance(data, list):
        return [row for item in data for row in reports(item)]
    return [data] if isinstance(data, dict) and data.get('OrdStatus') and data.get('ClOrdID') else []


def exec_id(location, symbol, maker, taker, role):
    key = '\x1f'.join([location, symbol, maker, taker, '0', role])
    return 'E' + hashlib.sha256(key.encode()).hexdigest()[:30]


def signed_actor(location, symbol, mode, run, index, accounts):
    from opentradingcore import OpenTradingCoreClient
    trader = CANCEL['new_trader'](location, symbol, mode, run, index)
    issued = CANCEL['api']('LoginSvr', 'updateApiKey', {
        'cid': 'MULTI_KEY_' + run + str(index), 'label': 'multi-maker-' + run, 'type': 'trade'}, trader[2])
    entry = {'trader': trader, 'key': issued['api_key'], 'client': None, 'symbol': symbol}
    accounts.append(entry)
    client = OpenTradingCoreClient.from_api_key(
        base_url=CANCEL['URL'].rsplit('/httpapi/', 1)[0], location=location,
        api_key=issued['api_key'], api_secret=issued['secret_key'], timeout=8)
    entry['client'] = client
    session = client.login(mode='trader')
    if session.user_id != trader[1] or session.client_type != 'API':
        raise RuntimeError('Signed test identity mismatch')
    return client


def place(client, symbol, side, qty, price, tif, cid):
    return client.call('OrderSvr', 'placeOrder', {
        'Location': client.session.location, 'UserID': client.session.user_id, 'SecurityID': symbol,
        'MarketIndicator': '4', 'OCType': 'OPEN', 'Side': side, 'OrdType': 'Limit',
        'TimeInForce': tif, 'OrderQty': str(D(qty)), 'Price': price, 'ClOrdID': cid,
        'Terminal': 'API', 'AlgoName': 'cross', 'Demo': '0'},
        routing_key=client.session.location + '\x1f4\x1f' + symbol)


def trader(client):
    return client.session.location, client.session.user_id, client.session.token


def clean(accounts, prefix, result):
    for actor_index, entry in enumerate(accounts):
        client = entry['client']
        if client is not None:
            try:
                for row in CANCEL['open_orders'](trader(client), entry['symbol']):
                    cid = row.get('ClOrdID') or row.get('ClOrderID')
                    if not cid or not cid.startswith(prefix):
                        raise RuntimeError('Order outside the test ownership boundary')
                    CANCEL['cancel'](trader(client), entry['symbol'],
                                     {'order_id': row['OrderID'], 'client_order_id': cid})
                    CANCEL['await_order'](trader(client), entry['symbol'], cid, False)
                if result['mode'] == 'TRADE':
                    balance, position = client.balances(), client.positions(entry['symbol'])
                    fees = PRODUCT['readonly_sql']("SELECT COALESCE(SUM(fee),0),COUNT(*),COUNT(fee) FROM dc_orders_execorders "
                        f"WHERE location='{client.session.location}' AND user_id='{client.session.user_id}'")
                    side = 'ShortPosition' if actor_index == 0 else 'LongPosition'
                    opposite = 'LongPosition' if actor_index == 0 else 'ShortPosition'
                    financial = {'user_id': client.session.user_id, 'balance': balance, 'position': position,
                                 'sum_execution_fees': fees[0][0]}
                    result.setdefault('financial_after_normal_cleanup', []).append(financial)
                    if (D(str(balance['FreezedMargin'])) != 0 or D(str(balance['FreezedCommission'])) != 0
                            or D(str(balance['Balance'])) != D('10000') + D(fees[0][0])
                            or int(fees[0][1]) != (2 if D(result['expected_quantity']) > 0 else 0)
                            or fees[0][1] != fees[0][2]
                            or D(str(position[side])) != D(result['expected_quantity'])
                            or D(str(position[opposite])) != 0
                            or D(str(balance['UsedMargin'])) != D(str(position['LongUsedMargin'])) + D(str(position['ShortUsedMargin']))):
                        raise RuntimeError('Exact balance, fees, reservation or position mismatch')
                client.close_stream(channel='private')
            except Exception as error:
                result.setdefault('cleanup_errors', []).append(type(error).__name__)
        try:
            deleted = CANCEL['PRODUCT']['call'](CANCEL['URL'], 'LoginSvr', 'deleteApiKey', {
                'cid': prefix + '-KEY-DELETE', 'api_key': entry['key']}, entry['trader'][2])
            if deleted.get('code') != 0:
                raise RuntimeError('Key revocation failed')
        except Exception as error:
            result.setdefault('cleanup_errors', []).append(type(error).__name__)


def run_case(root, location, mode, symbol, run, index, case, result):
    name, tif, qty, expected_qty, expected_status = case
    prefix = f'T554MM-{run}-{index}'
    result.update(name=name, mode=mode, symbol=symbol, location=location, prefix=prefix,
                  expected_quantity=expected_qty, expected_status=expected_status, passed=False)
    accounts, collected, errors = [], [], []
    done, guard = Event(), Lock()
    receivers = []
    try:
        maker = signed_actor(location, symbol, mode, run, str(index) + 'm', accounts)
        taker = signed_actor(location, symbol, mode, run, str(index) + 't', accounts)
        result['users'] = [maker.session.user_id, taker.session.user_id]
        websocket_port = CAPACITY['FRESH']['env_pairs'](root / 'demo.env')['GW_WEBSOCKET_PORT']
        for client in (maker, taker):
            result['stage'] = 'CONNECT_PRIVATE_' + client.session.user_id
            client.connect_stream('private', gateway_base_url='http://127.0.0.1:' + websocket_port)
            client.subscribe_executions(symbol)
            client.subscribe_order_status(symbol)

            def receive(client=client):
                from websocket import WebSocketTimeoutException
                while not done.is_set():
                    try:
                        for event in client.events(channel='private'):
                            if done.is_set():
                                return
                            for report in reports(event.get('data')):
                                if report['ClOrdID'].startswith(prefix):
                                    with guard:
                                        collected.append(report)
                    except WebSocketTimeoutException:
                        continue
                    except Exception as error:
                        if not done.is_set():
                            errors.append(type(error).__name__)
                        return
            receiver = Thread(target=receive, daemon=True)
            receivers.append(receiver)
            receiver.start()

        cids = [prefix + '-M1', prefix + '-M2', prefix + '-T']
        maker_orders = []
        for cid, price in zip(cids[:2], ['90000', '90001']):
            result['stage'] = 'PLACE_MAKER_' + cid
            place(maker, symbol, 'Sell', '.0003', price, 'GTC', cid)

            def resting(cid=cid):
                rows = CANCEL['own_order'](CANCEL['open_orders'](trader(maker), symbol), cid)
                return rows[0] if len(rows) == 1 and str(rows[0].get('Maker')).lower() in ('true', '1') else None
            maker_orders.append(wait(resting, 'Maker did not reach the authoritative resting book'))
        result['stage'] = 'PLACE_TAKER'
        place(taker, symbol, 'Buy', qty, '90002', tif, cids[2])

        def terminal():
            with guard:
                return next((row for row in reversed(collected) if row['ClOrdID'] == cids[2]
                             and row['OrdStatus'] == expected_status and D(str(row.get('CumQty', -1))) == D(expected_qty)), None)
        result['stage'] = 'WAIT_PRIVATE_TERMINAL'
        result['taker_final_push'] = wait(terminal, 'Expected actual private terminal/partial push did not arrive')
        live = CANCEL['own_order'](CANCEL['open_orders'](trader(taker), symbol), cids[2])
        if name == 'GTC_PARTIAL':
            def resting_taker():
                rows = CANCEL['own_order'](CANCEL['open_orders'](trader(taker), symbol), cids[2])
                return rows[0] if len(rows) == 1 and str(rows[0].get('Maker')).lower() in ('true', '1') else None
            result['resting_taker_residual'] = wait(resting_taker, 'GTC residual did not become a resting maker')
            CANCEL['cancel'](trader(taker), symbol, {'order_id': result['resting_taker_residual']['OrderID'], 'client_order_id': cids[2]})
            CANCEL['await_order'](trader(taker), symbol, cids[2], False)
        elif live:
            raise RuntimeError('Immediate order remains open after its terminal push')

        expected_legs = [] if D(expected_qty) == 0 else [D('.0003'), D(expected_qty) - D('.0003')]
        taker_id = result['taker_final_push']['OrderID']
        expected = {}
        for order, amount in zip(maker_orders, expected_legs):
            for role, user in [('maker', maker.session.user_id), ('taker', taker.session.user_id)]:
                eid = exec_id(location, symbol, str(order['OrderID']), str(taker_id), role)
                expected[eid] = (user, amount, D(str(order['Price'])))

        def actual_executions():
            with guard:
                rows = [row for row in collected if row.get('ExecType') == 'Trade' and row.get('ExecID')]
            unique = {}
            for row in rows:
                identity = row['ExecID']
                economic = (row.get('UserID'), D(str(row['LastQty'])), D(str(row['LastPx'])))
                if identity in unique and unique[identity] != economic:
                    raise RuntimeError('Repeated execution changed economic values')
                unique[identity] = economic
            return unique
        if expected:
            wait(lambda: actual_executions() == expected, 'Private maker/taker executions differ from every exact leg')
        elif actual_executions():
            raise RuntimeError('Unfilled FOK/PO generated a partial execution')
        with guard:
            result['private_reports'] = list(collected)
        result['expected_execution_ids'] = sorted(expected)

        def projected():
            orders = PRODUCT['readonly_sql']("SELECT clord_id,ord_status,cum_qty FROM dc_orders "
                f"WHERE location='{location}' AND clord_id='{cids[2]}'")
            status = 'Cancelled' if name == 'GTC_PARTIAL' else expected_status
            executions = PRODUCT['readonly_sql']("SELECT exec_id,user_id,last_qty,last_px FROM dc_orders_execorders "
                f"WHERE location='{location}' AND order_id IN (SELECT order_id FROM dc_orders "
                f"WHERE location='{location}' AND clord_id LIKE '{prefix}-%')")
            exact = {row[0]: (row[1], D(row[2]), D(row[3])) for row in executions}
            if (len(orders) == 1 and orders[0][1] == status and D(orders[0][2]) == D(expected_qty)
                    and len(executions) == len(expected) and exact == expected):
                return {'orders': orders, 'executions': executions}
        result['projection'] = wait(projected, 'Order/execution SQL projection is not exact')
        if expected and mode == 'TRADE':
            ids = ','.join("'" + eid + "'" for eid in sorted(expected))

            def financial_group():
                rows = PRODUCT['readonly_sql']("SELECT partition_id,source_epoch,journal_seq,source_type,COUNT(*) "
                    "FROM dc_trade_projection_mutation "
                    f"WHERE location='{location}' AND entity_type='POSTING' "
                    f"AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.sourceID')) IN ({ids}) "
                    "GROUP BY partition_id,source_epoch,journal_seq,source_type")
                return rows if len(rows) == 1 and rows[0][3] == 'TRADE_ATOMIC_MATCH_GROUP_PREPARED' and int(rows[0][4]) == len(expected) else None
            result['one_financial_wal_group'] = wait(financial_group, 'Expected one atomic financial WAL group for all legs')

        def public_trades():
            market = CANCEL['api']('MDSvr', 'queryPublicMarket', {'location': location, 'securityID': symbol})
            rows = market.get('recentTrades', {}).get('NoMDEntries', [])
            selected = [row for row in rows if row.get('MDEntryID') in expected]
            ids = Counter(row['MDEntryID'] for row in selected)
            wanted = {exec_id(location, symbol, str(order['OrderID']), str(taker_id), 'maker') for order in maker_orders[:len(expected_legs)]}
            if set(ids) == wanted and all(count == 1 for count in ids.values()) and all(
                    (D(str(row['MDEntrySize'])), D(str(row['MDEntryPx']))) == expected[row['MDEntryID']][1:] for row in selected):
                return {'passed': True, 'entries': selected}
        result['public_trades'] = wait(public_trades, 'Public market does not contain exactly one trade per match leg')
        result['passed'] = not errors
    finally:
        done.set()
        clean(accounts, prefix, result)
        for receiver in receivers:
            receiver.join(timeout=2)
        result['stream_errors'] = errors
        result['passed'] = result.get('passed', False) and not errors and not result.get('cleanup_errors')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('generation', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    root = args.generation.resolve(strict=True)
    sys.path.insert(0, str(HERE.parent / '.work/fresh-fullflow-20261021/sdk019/deployed-install'))
    from opentradingcore import OpenTradingCoreClient  # noqa: F401
    CAPACITY['require_strict_demo'](root)
    run = secrets.token_hex(4)
    report = {'generation': root.name, 'run': run, 'passed': False, 'cases': [],
              'common_release': CAPACITY['common_release_identity'](root),
              'started_at': datetime.now(timezone.utc).isoformat(),
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    output = root / ('multi-maker-' + run + '.json')
    try:
        with (root.parent / '.mac-demo-fresh.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = CAPACITY['require_strict_demo'](root)
            with CANCEL['controlled_products'](run, report) as (location, products):
                for mode, symbol in sorted(products, key=lambda product: product[0] != 'TRADE'):
                    for case in CASES:
                        row = {}
                        report['cases'].append(row)
                        run_case(root, location, mode, symbol, run, len(report['cases']), case, row)
                        output.write_text(json.dumps(report, indent=2) + '\n')
                        print(mode, case[0], 'PASS' if row['passed'] else 'NO_GO', flush=True)
                        if not row['passed']:
                            raise RuntimeError('Real multi-maker case failed')
            code, financial, checks = CAPACITY['reconcile_financial_cursor']()
            report.update(financial_cursor=financial, financial_cursor_checks=checks,
                          control_stable=before == CAPACITY['require_strict_demo'](root))
            report['passed'] = code == 0 and report['control_stable'] and len(report['cases']) == 12 and all(row['passed'] for row in report['cases'])
    except Exception as error:
        report['failure_type'] = type(error).__name__
        code = re.search(r'code=([A-Za-z0-9_-]+)', str(error))
        report['failure_code'] = code[1] if code else None
        report['failure_stack'] = [{'file': Path(frame.filename).name, 'line': frame.lineno,
                                    'function': frame.name} for frame in traceback.extract_tb(error.__traceback__)[-4:]]
        # Error text is deliberately bounded to our own validation messages.
        if type(error) is RuntimeError and str(error).startswith(('Expected ', 'Maker ', 'Private ', 'Immediate ', 'Order/', 'Public ', 'GTC ', 'Real ', 'Unfilled ', 'Repeated ')):
            report['failure'] = str(error)
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        output.write_text(json.dumps(report, indent=2) + '\n')
    print(('PASS' if report['passed'] else 'NO_GO') + ' ' + str(output), flush=True)
    return 0 if report['passed'] else 2


if __name__ == '__main__':
    sys.exit(main())
