"""Read-only exact ACTIVE source backup for independent-mechanism release review.

Private generated sources stay outside the public deployment checkout.
"""
import argparse
import base64
import hashlib
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import paramiko

from recovery.local_strategy_backtest import DEFAULT_HOST, DEFAULT_USER, DEFAULT_KEY
from recovery.prod_gateway_tunnel import ForwardHandler, ForwardServer
from recovery.strategy_recovery_common import BACKUP_TOPIC, atomic_write_json, call_gateway


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if (output / 'manifest.json').exists():
        raise ValueError('peer snapshot already frozen; use a new directory')
    client, server = paramiko.SSHClient(), None
    client.load_host_keys(str(Path.home() / '.ssh/known_hosts'))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        client.connect(DEFAULT_HOST, username=DEFAULT_USER, key_filename=DEFAULT_KEY,
            passphrase=os.environ.pop('STC_PROD_KEY_PASSPHRASE'), look_for_keys=False,
            allow_agent=False, timeout=20)
        client.get_transport().set_keepalive(20)
        _, stdout, stderr = client.exec_command('hostname', timeout=20)
        hostname, error = stdout.read().decode().strip(), stderr.read().decode()
        if stdout.channel.recv_exit_status() or hostname != 'prod-mooncake-standby':
            raise ValueError('unexpected read-only peer source host')
        ForwardHandler.transport, ForwardHandler.remote_port = client.get_transport(), 31002
        server = ForwardServer(('127.0.0.1', 0), ForwardHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        result = call_gateway('http://127.0.0.1:%d/gw' % server.server_address[1],
            os.environ.get('DC_GW_APIKEY', '1'), BACKUP_TOPIC,
            {'scope': 'live_only', 'limit': 2000}, timeout=180, attempts=1)
        package = result.get('packageData') or {}
        if package.get('packageType') != 'live_strategy_backup':
            raise ValueError('unexpected live source backup contract')
        candidates = {(row['strategyName'], row['strategyVersion']): row
                      for row in package.get('candidateRows', [])}
        active = {(row['strategyName'], row['strategyVersion']): row
                  for row in package.get('registryRows', []) if str(row.get('status')).upper() == 'ACTIVE'}
        records = []
        for key, row in sorted(active.items()):
            candidate = candidates.get(key) or {}
            source = base64.b64decode(candidate.get('javaSourceContentBase64') or '', validate=True)
            if not source:
                raise ValueError('exact active source missing: ' + '@'.join(key))
            folder = output / hashlib.sha256('@'.join(key).encode()).hexdigest()[:16]
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / 'GeneratedStrategy.java'
            path.write_bytes(source)
            records.append({'strategy': key[0], 'version': key[1], 'symbol': row.get('symbolScope'),
                'scene': row.get('scene'), 'source_sha256': hashlib.sha256(source).hexdigest(),
                'source_path': str(path), 'source_bytes': len(source)})
        atomic_write_json(output / 'manifest.json', {'schema': 'active_peer_source_review_v1',
            'snapshot_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'export_time': package.get('exportTime'), 'peers': records,
            'production_write': False, 'trade_or_risk_changes': False, 'code_generation_calls': 0})
        for record in records:
            print('ACTIVE_PEER', record['strategy'], record['version'], record['source_sha256'], flush=True)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        client.close()


if __name__ == '__main__':
    main()
