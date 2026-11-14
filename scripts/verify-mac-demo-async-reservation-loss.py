#!/usr/bin/env python3
"""Verify normal cancellation after a genuinely unreplicated Trade reservation is lost."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import hashlib
import json
import os
from pathlib import Path
import runpy
import secrets
import signal
import time
import zlib

HERE = Path(__file__).resolve().parent
RPO = runpy.run_path(str(HERE / 'verify-mac-demo-async-rpo.py'))
CANCEL, CAPACITY, PRODUCT = RPO['CANCEL'], RPO['CAPACITY'], RPO['PRODUCT']
run, inspect, until, manifest = (RPO[key] for key in ('run', 'inspect', 'until', 'manifest'))
ROBOT = RPO['ROBOT']


def account(trader):
    location, user, token = trader
    row = PRODUCT['ok'](RPO['URL'], 'TradeSvr', 'queryAccountBalance',
                        {'location': location, 'userid': user}, token, route_location=location)
    fields = ('Balance', 'UsedMargin', 'FreezedMargin', 'FreezedCommission')
    if not isinstance(row, dict) or any(row.get(key) is None for key in fields):
        raise RuntimeError('Live account reply is missing an exact financial field')
    values = {key: Decimal(str(row[key])) for key in fields}
    if not all(value.is_finite() for value in values.values()):
        raise RuntimeError('Live account reply has a non-finite financial value')
    return {key: str(value.normalize()) for key, value in values.items()}


def terminal_cancel_mutations(location, order_id):
    return PRODUCT['readonly_sql'](
        "SELECT partition_id,source_epoch,journal_seq,entity_type,operation,payload "
        "FROM dc_trade_projection_mutation "
        f"WHERE location='{location}' AND request_id='{order_id}:Trade_Cancel' "
        "AND source_type='CANCEL_OPEN_PREPARED' ORDER BY source_epoch,journal_seq,mutation_index")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('generation', type=Path)
    parser.add_argument('--tools', type=Path,
                        default=Path.home() / '.opentradingcore/t554-rpo-delivery-fault-agent-20261112-v2')
    args = parser.parse_args()
    root = args.generation.resolve(strict=True)
    os.umask(0o077)
    with (RPO['FRESH']['LOCAL'] / '.mac-demo-fresh.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        CAPACITY['require_strict_demo'](root)
        release = CAPACITY['common_release_identity'](root)
        if release['client_ack_policy'] != 'LOCAL_DURABLE_ASYNC':
            raise RuntimeError('Reservation loss requires normal dual-node asynchronous confirmation')
        for name in ('head-observer-self-test.status', 'head-observer-linux-self-test.status'):
            if (args.tools / name).read_text().strip() != 'PASS':
                raise RuntimeError('The read-only physical head observer has not passed its release tests')
        initial = {kind: manifest(root, kind) for kind in ('order', 'trade')}
        baseline = CAPACITY['demo_tenants']()
        if not baseline or not all(value == 'RUNNING' for value in baseline.values()):
            raise RuntimeError('The original Robot cohort must be running before this case')
        robot_before = inspect('dc-saas-robotsvr')
        run_id = secrets.token_hex(4)
        output = root / ('async-reservation-loss-' + run_id)
        output.mkdir(mode=0o700)
        record = {'status': 'NO_GO', 'generation': root.name, 'common_release': release,
                  'initial': initial, 'started_at': datetime.now(timezone.utc).isoformat(),
                  'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  'rpo_helper_sha256': hashlib.sha256((HERE / 'verify-mac-demo-async-rpo.py').read_bytes()).hexdigest()}

        def save():
            pending = output / 'evidence.pending'
            pending.write_text(json.dumps(record, indent=2) + '\n')
            pending.replace(output / 'evidence.json')

        save()
        primary = backup = None
        policy_overridden = False
        killed = False
        local = None
        failure = None
        trader = None
        password = secrets.token_urlsafe(24)
        admin_password = secrets.token_urlsafe(24)
        since = None
        try:
            with CANCEL['controlled_products'](run_id, record, admin_password) as (location, products):
                symbol = next(symbol for mode, symbol in products if mode == 'TRADE')
                partition = 'P%03d' % (zlib.crc32(location.encode()) % 256)
                if any(zlib.crc32(other.encode()) % 256 == int(partition[1:]) for other in baseline):
                    raise RuntimeError('Controlled reservation partition collides with the active Robot cohort')
                trader = CANCEL['new_trader'](location, symbol, 'TRADE', run_id, 0, password)
                primary_slot = initial['trade'][partition]['primary'][-1]
                backup_slot = 'B' if primary_slot == 'A' else 'A'
                epoch = initial['trade'][partition]['epoch']
                primary = f'{root.name}-trade-{primary_slot.lower()}-hostready'
                backup = f'{root.name}-trade-{backup_slot.lower()}-hostready'
                order_partition = 'P%03d' % (zlib.crc32((location + '\x1f4\x1f' + symbol).encode()) % 256)
                order_slot = initial['order'][order_partition]['primary'][-1].lower()
                order_node = f'{root.name}-order-{order_slot}-hostready'
                order_before = inspect(order_node)
                backup_before = inspect(backup)
                original_policy = inspect(primary)['HostConfig']['RestartPolicy']
                if original_policy != {'Name': 'on-failure', 'MaximumRetryCount': 0}:
                    raise RuntimeError('Expected the existing unlimited on-failure restart policy')
                record.update(location=location, user=trader[1], symbol=symbol, partition=partition,
                              epoch=epoch, primary=primary, backup=backup, original_restart_policy=original_policy,
                              account_before=account(trader))
                tools_path = '/tmp/t554-reservation-loss-tools-' + run_id
                target_pids = {}
                for node in (primary, backup):
                    run('docker', 'exec', node, 'mkdir', '-m', '700', tools_path)
                    for name in ('head-observer.jar', 'T554RpoAttach.class'):
                        run('docker', 'cp', str(args.tools / name), node + ':' + tools_path + '/' + name)
                    jvms = run('docker', 'exec', node, '/opt/java/openjdk/bin/jps', '-l').splitlines()
                    pids = [line.split()[0] for line in jvms if 'sun.tools.jps.Jps' not in line]
                    if len(pids) != 1:
                        raise RuntimeError('Expected one unique physical Trade JVM')
                    target_pids[node] = pids[0]

                def certified_before():
                    try:
                        a, head = RPO['copy_wal'](primary, primary_slot, partition, output / 'primary-before.wal', epoch)
                        b, other = RPO['copy_wal'](backup, backup_slot, partition, output / 'backup-before.wal', epoch)
                    except RPO['IncompleteWalObservation']:
                        return None
                    if not head or a != b or head != other:
                        return None
                    prefix = hashlib.sha256(a).hexdigest()
                    expected = f'READY epoch={epoch} sequence={head} sha256={prefix} pending=false'
                    observations = {node: RPO['observe_physical_head'](
                        node, target_pids[node], tools_path, partition, head, prefix, epoch)
                        for node in (primary, backup)}
                    record['authenticated_pre_fault_heads'] = observations
                    save()
                    return (a, head) if all(value == expected for value in observations.values()) else None

                before_raw, before_head = until(certified_before, 30, 'Funding did not reach both authenticated physical heads')
                robot_location = next(other for other in sorted(baseline)
                    if initial['trade']['P%03d' % (zlib.crc32(other.encode()) % 256)]['primary'] == 'TradeSvr' + primary_slot)
                order_nodes = [f'{root.name}-order-{slot}-hostready' for slot in 'ab']
                trade_nodes = [f'{root.name}-trade-{slot}-hostready' for slot in 'ab']
                record['robot_before_fault'] = ROBOT['wait_traffic'](
                    order_nodes, trade_nodes, datetime.now(timezone.utc), robot_location)
                RPO['require_pause_lease_budget'](root / 'common/config-hostready/trade' / primary_slot / 'application.properties')
                watchdog = RPO['arm_pause_watchdog'](backup_before['Id'], output)
                policy_overridden = True
                run('docker', 'update', '--restart', 'no', primary)
                client = 'T554RESLOSS-' + run_id
                since = datetime.now(timezone.utc)
                begun = time.monotonic()
                try:
                    run('docker', 'pause', backup)
                    RPO['place'](trader, symbol, 'Buy', client, 'GTC')

                    def live_resting_order():
                        rows = CANCEL['own_order'](CANCEL['open_orders'](trader, symbol), client)
                        return rows[0] if len(rows) == 1 and rows[0].get('OrdStatus') == 'New' else None

                    order = until(live_resting_order, 2, 'Order did not observe New within the bounded replica pause')
                    if not inspect(backup)['State']['Paused']:
                        raise RuntimeError('Replica pause ended before the confirmed reservation fault')
                    record.update(client_order_id=client, order_id=order['OrderID'], order_new=order)
                    save()
                    run('docker', 'kill', '--signal', 'KILL', primary)
                    killed = True
                    stopped = inspect(primary)['State']
                    if stopped['Running'] or stopped['ExitCode'] != 137:
                        raise RuntimeError('Original Trade primary did not exit with SIGKILL')
                    raw, backup_head = RPO['copy_wal'](backup, backup_slot, partition, output / 'backup-paused.wal', epoch)
                    if raw != before_raw or backup_head != before_head:
                        raise RuntimeError('The supposedly lost reservation reached the backup')
                    record.update(killed_primary=stopped, backup_certified_head=before_head)
                finally:
                    if inspect(backup)['State']['Paused']:
                        run('docker', 'unpause', backup)
                    record['replica_pause_seconds'] = round(time.monotonic() - begun, 6)
                    save()
                if watchdog.wait(timeout=5) != 0:
                    raise RuntimeError('The bounded replica pause watchdog failed')
                primary_raw, primary_head = RPO['copy_wal'](primary, primary_slot, partition, output / 'primary-local-acked.wal', epoch)
                if primary_head != before_head + 1 or not primary_raw.startswith(before_raw):
                    raise RuntimeError('Expected exactly one genuine locally acknowledged reservation frame')
                if order['OrderID'].encode() not in primary_raw[len(before_raw):]:
                    raise RuntimeError('Lost physical reservation does not identify the observed Order')
                record['primary_local_acked_head'] = primary_head
                local = RPO['wait_roles'](root, 'TradeSvr' + backup_slot)
                record['survivor_local'] = local
                if inspect(backup)['State']['StartedAt'] != backup_before['State']['StartedAt']:
                    raise RuntimeError('The surviving backup unexpectedly restarted')
                record['robot_while_local'] = ROBOT['wait_traffic'](
                    order_nodes, [backup], datetime.now(timezone.utc), robot_location, local)
                trader = RPO['refresh_trader'](trader, run_id, 0, password)
                record['account_after_certified_takeover_before_cancel'] = account(trader)
                if record['account_after_certified_takeover_before_cancel'] != record['account_before']:
                    raise RuntimeError('The lost reservation altered recovered funds before cancellation')
                CANCEL['cancel'](trader, symbol, {'order_id': order['OrderID'], 'client_order_id': client})
                CANCEL['await_order'](trader, symbol, client, False)

                def cancelled_batch():
                    rows = terminal_cancel_mutations(location, order['OrderID'])
                    if not rows:
                        return None
                    if len(rows) != 2 or {(row[3], row[4]) for row in rows} != {
                            ('OPEN_ORDER', 'REMOVE'), ('DEDUPE_RESULT', 'UPSERT')}:
                        raise RuntimeError('Lost reservation cancel did not persist exactly the two terminal mutations')
                    if len({tuple(row[:3]) for row in rows}) != 1 or int(rows[0][1]) != local[partition]['epoch']:
                        raise RuntimeError('Cancel mutations do not share the genuine LOCAL commit coordinate')
                    receipt = json.loads(next(row[5] for row in rows if row[3] == 'DEDUPE_RESULT'))
                    result = receipt['result']
                    if result.get('info3') != 'LOCAL_DURABLE_ASYNC' or result.get('info4') != '/'.join(rows[0][:3]):
                        raise RuntimeError('Persisted cancellation receipt lost its real local durability coordinate')
                    return rows

                record['local_cancel_mutations'] = until(cancelled_batch, 60, 'Terminal cancellation did not reach the certified projection')
                record['account_after_cancel'] = account(trader)
                if record['account_after_cancel'] != record['account_before']:
                    raise RuntimeError('Cancellation fabricated a second financial release')
                record['local_business_consistent'] = True
                save()
        except BaseException as error:
            failure = error
            record['failure'] = type(error).__name__ + ': ' + str(error)
        finally:
            try:
                if backup and inspect(backup)['State']['Paused']:
                    run('docker', 'unpause', backup)
                if primary and record.get('order_id') and not inspect(primary)['State']['Running']:
                    killed = True
                if killed:
                    if local is None:
                        local = RPO['wait_roles'](root, 'TradeSvr' + backup_slot)
                        record['survivor_local'] = local
                    run('docker', 'update', '--restart', 'on-failure', primary)
                    run('docker', 'start', primary)
                    home = RPO['wait_roles'](root)
                    record['strict_home'] = home
                    hashes = [RPO['ROLL']['physical_hashes'](node, 'TradeSvr', slot, backup_slot, local, home)
                              for node, slot in ((primary, primary_slot), (backup, backup_slot))]
                    if hashes[0] != hashes[1] or len(hashes[0]) != 512:
                        raise RuntimeError('Returned physical WAL and snapshot pairs differ')
                    record['physical_pairs'] = 512
                    trader = RPO['refresh_trader'](trader, run_id, 0, password)
                    record['account_after_home'] = account(trader)
                    if record['account_after_home'] != record['account_before']:
                        raise RuntimeError('Original primary return resurrected or released the lost reservation')
                    if CANCEL['own_order'](CANCEL['open_orders'](trader, record['symbol']), record['client_order_id']):
                        raise RuntimeError('Cancelled order resurrected after the original primary returned')
                    code, financial, checks = CAPACITY['reconcile_financial_cursor']()
                    record.update(financial_cursor=financial, financial_checks=checks)
                    if code:
                        raise RuntimeError('Certified financial source and projection differ after return')
                    record['robot_local_postings'] = ROBOT['require_posting_pairs'](record['robot_while_local'])
                    robot_after = inspect('dc-saas-robotsvr')
                    record['same_robot_process'] = (robot_before['Id'] == robot_after['Id']
                        and robot_before['State']['StartedAt'] == robot_after['State']['StartedAt'])
                    if not record['same_robot_process'] or inspect(order_node)['State']['StartedAt'] != order_before['State']['StartedAt']:
                        raise RuntimeError('Unrelated Order or Robot process restarted during the fault')
                    record['robot_during_fault'] = ROBOT['rounds'](robot_location, since, datetime.now(timezone.utc))
            except BaseException as error:
                record['recovery_failure'] = type(error).__name__ + ': ' + str(error)
                failure = failure or error
            finally:
                if policy_overridden:
                    try:
                        run('docker', 'update', '--restart', 'on-failure', primary)
                        record['restart_policy_restored'] = inspect(primary)['HostConfig']['RestartPolicy'] == original_policy
                        if not record['restart_policy_restored']:
                            raise RuntimeError('Original automatic restart contract was not restored')
                    except BaseException as error:
                        record['restart_policy_failure'] = type(error).__name__ + ': ' + str(error)
                        failure = failure or error
            if failure is None and record.get('local_business_consistent') and record.get('physical_pairs') == 512:
                record['status'] = 'UNREPLICATED_RESERVATION_LOSS_NORMAL_CANCEL_FUNDS_AND_HOME_PASS'
            record['finished_at'] = datetime.now(timezone.utc).isoformat()
            save()
        print('[mac-demo reservation loss]', record['status'], output, flush=True)
        if failure is not None:
            raise failure
        if record['status'] == 'NO_GO':
            raise RuntimeError('Controlled reservation-loss verification did not finish')


if __name__ == '__main__':
    def terminate(signum, frame):
        raise KeyboardInterrupt('Reservation loss driver termination requested')

    signal.signal(signal.SIGTERM, terminate)
    main()
