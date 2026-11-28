"""Measure native TCP final receipts on a clean installation with ten funded Robots."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
SECONDS = 60


def publish(title, summary):
    text = json.dumps(summary, ensure_ascii=True, indent=2)
    with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a') as stream:
        stream.write(f'## {title}\n\n```json\n{text}\n```\n')
    print(title, text, flush=True)


def book_prices(cancel, location, symbol):
    market = cancel['api']('MDSvr', 'queryPublicMarket', {'location': location, 'securityID': symbol})
    entries = market['orderBook']['NoMDEntries']
    sides = {side: [Decimal(str(row['MDEntryPx'])) for row in entries
                    if str(row['MDEntryType']) == side and Decimal(str(row['MDEntrySize'])) > 0] for side in ('0', '1')}
    bid, ask = max(sides['0']), min(sides['1'])
    if not 0 < bid < ask:
        raise ValueError('Expected a two-sided live BTCUSDT book')
    # Keep GTC cancel orders off the touch. Provide a funded sell limit behind
    # the public maker to cover the complete IOC window even if its quote moves.
    return (str((bid * Decimal('0.95')).to_integral_value(rounding=ROUND_DOWN)),
            str((ask * Decimal('1.005')).to_integral_value(rounding=ROUND_UP)))


def synchronized_clients(native, work, configs):
    barrier = int(time.time() * 1000) + 20000
    with ThreadPoolExecutor(max_workers=len(configs)) as clients:
        jobs = [clients.submit(native['run'], work, dict(c, start_at_epoch_ms=barrier)) for c in configs]
        return [job.result() for job in jobs]


def measure_target(harness, work, cancel_work, locations, port, policy):
    cancel, native, execution = harness['CANCEL'], harness['NATIVE'], harness['EXEC']
    symbol = 'BTCUSDT'
    sessions, cancel_configs, fill_configs = [], [], []
    rate = 65
    run = secrets.token_hex(4)
    with ExitStack() as owned:
        for index in range(16):
            location = locations[index % len(locations)]
            stream = run + format(index, '02x')
            maker = cancel['new_trader'](location, symbol, 'TRADE', stream, 0, funding_amount=100000)
            trader = cancel['new_trader'](location, symbol, 'TRADE', stream, 1, funding_amount=100000)
            _, _, token = owned.enter_context(cancel['native_trader_session'](trader, stream, index))
            passive, _ = book_prices(cancel, location, symbol)
            config = dict(location=location, user_id=trader[1], symbol=symbol, port=port, seconds=SECONDS, token=token)
            cancel_configs.append(dict(config, prefix='T554CC-'+stream, price=passive, max_requests_per_second=80))
            sessions.append((maker, stream, config))

        responses = synchronized_clients(native, cancel_work, cancel_configs)
        rows = [row for response in responses for row in response['orders']]
        phase = dict(records=rows, window_seconds=SECONDS,
                     passed=all(r['orders'] and r['measurement_complete'] and not r['stream_errors'] for r in responses)
                     and all(r.get('passed') is True for r in rows)
                     and len({r['client_order_id'] for r in rows}) == len(rows))
        for field in ('place_new_ms', 'cancel_terminal_ms', 'cancel_pending_ms'):
            phase[field] = execution['summary_ms'](rows, field)
        cancel_target = cancel['PERFORMANCE']['order_cancel_target'](phase, 'tcp')
        publish(f'{policy} funded multi-tenant place and cancel', {
            'sessions': len(sessions), 'tenants': len(set(locations)), 'cycles': len(rows),
            'new': phase['place_new_ms'], 'pending': phase['cancel_pending_ms'],
            'cancelled': phase['cancel_terminal_ms'], 'acceptance': cancel_target})
        if not phase['passed']:
            raise RuntimeError('Multi-tenant place and cancel receipts failed to reconcile')

        def retire_cover(maker, client_id):
            resting = cancel['own_order'](cancel['open_orders'](maker, symbol), client_id)
            if resting:
                cancel['cancel'](maker, symbol, dict(order_id=resting[0]['OrderID'], client_order_id=client_id))
            cancel['await_order'](maker, symbol, client_id, False)

        for index, (maker, stream, config) in enumerate(sessions):
            location = config['location']
            _, cover = book_prices(cancel, location, symbol)
            client_id = 'T554EXEC-' + stream + '-MAKER'
            cancel['api']('OrderSvr', 'placeOrder', dict(Location=location, SecurityID=symbol, MarketIndicator='4',
                UserID=maker[1], Side='Sell', Price=cover, OrderQty=str(execution['QUANTITY']*(rate*SECONDS+1)),
                OCType='OPEN', OrdType='Limit', TimeInForce='GTC', ClOrdID=client_id, Terminal='API',
                AlgoName='cross', Demo='0', ReduceOnly='false'), maker[2])
            owned.callback(retire_cover, maker, client_id)
            cancel['await_order'](maker, symbol, client_id, True)
            fill_configs.append(dict(config, price=cover, rate=rate, quantity=str(execution['QUANTITY']),
                run=stream, arrival_offset_ns=harness['arrival_offset_ns']('staggered', index, len(sessions), rate)))
        responses = synchronized_clients(native, work, fill_configs)
        streams = [dict(measurement=response, location=config['location'], symbol=symbol, run=config['run'])
                   for response, config in zip(responses, fill_configs)]
        aggregate = harness['_summarize_receipts'](streams, SECONDS, policy)
        harness['verify_stream_projections'](streams)
        consistent = all(s.get('projection', {}).get('consistent') is True for s in streams)
        cursor_code, _, _ = cancel['CAPACITY']['reconcile_financial_cursor']()
        accounts_match = True
        for stream, config in zip(streams, fill_configs):
            user, location = config['user_id'], config['location']
            if not re.fullmatch(r'[0-9]{1,32}', user) or not re.fullmatch(r'[A-Z0-9]{6}', location):
                raise ValueError('Invalid funded test identity')
            expected = sum(bool(row.get('execution_id')) for row in stream['measurement']['orders'])
            rows = cancel['PRODUCT']['readonly_sql'](
                "SELECT t.fills FROM dc_users_balance b JOIN dc_orders_position p "
                "ON p.location=b.location AND p.user_id=b.user_id AND p.security_id='BTCUSDT' "
                "JOIN (SELECT e.location,e.user_id,COUNT(*) fills,SUM(e.last_qty) qty,SUM(e.fee) fees, "
                "COUNT(f.id) posted FROM dc_orders_execorders e LEFT JOIN dc_users_posting f "
                "ON f.id=CONCAT('E2TRADE-',SHA2(CONCAT_WS(CHAR(31),e.location,e.user_id,e.exec_id),256)) "
                "AND f.location=e.location AND f.user_id=e.user_id AND f.source_id=e.exec_id "
                "AND f.type=3 AND CAST(f.amount AS DECIMAL(36,12))=e.fee "
                f"WHERE e.location='{location}' AND e.user_id='{user}' AND e.exec_type='Trade' "
                "AND e.security_id='BTCUSDT' GROUP BY e.location,e.user_id) t "
                "ON t.location=b.location AND t.user_id=b.user_id WHERE "
                "t.fills=t.posted AND b.balance=100000+t.fees AND p.long_position=t.qty "
                "AND p.short_position=0 AND b.freezed_margin=0 AND b.freezed_commission=0")
            accounts_match = accounts_match and expected > 0 and rows == [[str(expected)]]
        target = cancel['PERFORMANCE']['execution_target'](
            aggregate, SECONDS, consistent and cursor_code == 0 and accounts_match)
        publish(f'{policy} funded multi-tenant final trade receipts', {
            'sessions': len(sessions), 'tenants': len(set(locations)), 'offered_per_second': rate * len(sessions),
            'aggregate': aggregate, 'projection_consistent': consistent, 'financial_cursor_reconciled': cursor_code == 0,
            'funded_accounts_reconciled': accounts_match, 'acceptance': target})
    return cancel_target['passed'] and target['passed']


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_OS') != 'Linux':
        raise RuntimeError('This measurement requires a disposable hosted Linux installation')
    policy = os.environ.get('T554_HOSTED_ACK_POLICY', 'STRICT_QUORUM')
    os.umask(0o077)
    base = Path(os.environ['RUNNER_TEMP']) / 't554-install'
    receipt = json.loads((base / 'installation.json').read_text())
    generation = os.environ['SIMULATION_GENERATION']
    if receipt['generation'] != generation or not re.fullmatch('sim-demo-[0-9]{8}-[0-9]{6}', generation):
        raise RuntimeError('The installed generation differs from the measurement')
    install = runpy.run_path(str(ROOT / 'scripts/install-public-simulation.py'))
    inventory = install['inventory'](generation)
    if receipt['runningImages'] != inventory:
        raise RuntimeError('Installed runtime differs from the verified receipt')
    directory = base / generation
    ports = install['simulation'].common.env_pairs(directory / 'demo.env')
    os.environ['OTC_CAPACITY_GATEWAY_HTTP_PORT'] = ports['GW_HTTP_PORT']
    harness = runpy.run_path(str(ROOT / 'scripts/verify-mac-demo-distributed-execution-capacity.py'))
    cancel, native, execution = harness['CANCEL'], harness['NATIVE'], harness['EXEC']
    symbol = 'BTCUSDT'
    baseline = cancel['CAPACITY']['demo_tenants']()
    if set(baseline) != set(receipt['tenants']) or len(baseline) != 10 or set(baseline.values()) != {'RUNNING'}:
        raise RuntimeError('Expected the ten funded background Robots')
    port = int(ports['GW_TCP_PORT'])
    work = native['prepare'](directory)
    cancel_work = native['prepare'](directory, ROOT / 'tests/MacDemoNativeTcpOrderCancel.java', 'MacDemoNativeTcpOrderCancel')
    run = secrets.token_hex(4)
    location = receipt['tenants'][0]
    maker = cancel['new_trader'](location, symbol, 'TRADE', run, 0, funding_amount=100000)
    trader = cancel['new_trader'](location, symbol, 'TRADE', run, 1, funding_amount=100000)
    cancel_price, _ = book_prices(cancel, location, symbol)
    config = dict(location=location, user_id=trader[1], symbol=symbol, port=port, seconds=SECONDS)
    with cancel['native_trader_session'](trader, run, 'cancel') as (_, _, token):
        measured = native['run'](cancel_work, dict(config, token=token, price=cancel_price,
                prefix='T554CC-'+run, max_requests_per_second=40, start_at_epoch_ms=int(time.time()*1000)+5000))
    rows = measured['orders']
    completed = bool(rows) and all(row.get('passed') is True for row in rows)
    commands = sum(int(row.get(k) is True) for row in rows for k in ('new_inside_window','cancel_inside_window'))
    publish(f'{policy} TCP place and cancel, one funded session', {
        'seconds': SECONDS, 'attempted_cycles': len(rows), 'commands_per_second': commands / SECONDS,
        'failures': dict(Counter(row.get('failure_reason', row.get('outcome', 'MISSING')) for row in rows if not row.get('passed'))),
        'successful_cycles': sum(row.get('passed') is True for row in rows),
        'new_ms': execution['summary_ms'](rows, 'place_new_ms'), 'cancel_ms': execution['summary_ms'](rows, 'cancel_terminal_ms'),
        'stream_errors': measured['stream_errors']})
    if not completed or measured['stream_errors'] or not measured['measurement_complete']:
        raise RuntimeError('Native place and cancel did not reconcile')
    for rate in (4, 16):
        window = secrets.token_hex(4)
        _, cover_price = book_prices(cancel, location, symbol)
        client_id = 'T554EXEC-' + window + '-MAKER'
        cancel['api']('OrderSvr','placeOrder',dict(Location=location, SecurityID=symbol, MarketIndicator='4',
                UserID=maker[1], Side='Sell', Price=cover_price, OrderQty=str(execution['QUANTITY'] * (rate*SECONDS+1)),
                OCType='OPEN', OrdType='Limit', TimeInForce='GTC', ClOrdID=client_id, Terminal='API',
                AlgoName='cross', Demo='0', ReduceOnly='false'), maker[2])
        order_id = cancel['await_order'](maker, symbol, client_id, True)
        try:
            with cancel['native_trader_session'](trader, window, 'fill') as (_, _, token):
                measured = native['run'](work, dict(config, token=token, rate=rate, run=window,
                        quantity=str(execution['QUANTITY']), price=cover_price, start_at_epoch_ms=int(time.time()*1000)+5000))
            row = dict(measurement=measured, location=location, symbol=symbol, run=window)
            aggregate = harness['_summarize_receipts']([row], SECONDS, policy)
            harness['verify_stream_projections']([row])
            consistent = row.get('projection', {}).get('consistent') is True
            publish(f'{policy} TCP final execution receipts at {rate}/s', {
                    'aggregate': aggregate, 'projection_consistent': consistent, 'offered_seconds': SECONDS})
            if not consistent or not aggregate['all_accepted_final_receipts_pass']:
                raise RuntimeError('Native final receipts or projected fills did not reconcile')
        finally:
            if cancel['own_order'](cancel['open_orders'](maker, symbol), client_id):
                cancel['cancel'](maker, symbol, dict(order_id=order_id, client_order_id=client_id))
            cancel['await_order'](maker, symbol, client_id, False)
    target_passed = True
    if os.environ.get('T554_HOSTED_TARGET_LOAD') == 'true':
        target_passed = measure_target(harness, work, cancel_work, receipt['tenants'], port, policy)
    if baseline != cancel['CAPACITY']['demo_tenants']() or install['inventory'](generation) != inventory:
        raise RuntimeError('A background Robot or runtime changed during measurement')
    if not target_passed:
        raise RuntimeError('Funded multi-tenant throughput or tail latency missed the target')


if __name__ == '__main__':
    main()
