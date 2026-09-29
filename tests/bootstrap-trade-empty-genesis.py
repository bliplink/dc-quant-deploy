#!/usr/bin/env python3
"""Fresh test install hook, invoked after ZK bootstrap and BEFORE any Trade starts."""
import argparse
import json
from pathlib import Path
import subprocess

from md_cluster_transition_host import DockerZk, parse_zk_get_many


class AuthenticatedZk(DockerZk):
    def _zk(self, command, timeout=90):
        result = subprocess.run(['docker', 'exec', '-i', '-e',
            'CLIENT_JVMFLAGS=-Djava.security.auth.login.config=/conf/jaas.ini', self.container,
            'zkCli.sh', '-server', self.server], input=command + '\nquit\n', text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=True)
        if 'KeeperErrorCode' in result.stdout or 'Exception' in result.stdout:
            raise ValueError('authenticated assignment read failed')
        return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', required=True, type=Path)
    parser.add_argument('--reset-proof', required=True, type=Path)
    parser.add_argument('--trade-image', required=True)
    parser.add_argument('--zk-port', required=True, type=int)
    args = parser.parse_args()
    root = args.runtime_root
    if str(root) not in {'/data/dc-saas-runtime', '/opt/dc-saas-runtime'} or root.resolve() != root:
        raise ValueError('unexpected test runtime root')
    running = subprocess.check_output(['docker', 'ps', '--format', '{{.Names}}'], text=True).split()
    allowed = {'dc-saas-mysql', 'dc-saas-zookeeper', 'dc-saas-clickhouse'}
    if any(name.startswith('dc-saas-') and name not in allowed for name in running):
        raise ValueError('genesis requires business services stopped')
    zk = AuthenticatedZk('dc-saas-zookeeper', f'127.0.0.1:{args.zk_port}', '/dc/cluster/tradesvr/partitions')
    rows = zk.read_many(f'P{index:03d}' for index in range(256))
    if any(row['version'] != 0 for row in rows):
        raise ValueError('fresh assignments must have untouched ZK dataVersion zero')
    assignment_file = args.reset_proof.with_suffix('.assignments.jsonl')
    with assignment_file.open('x') as output:
        for row in rows:
            output.write(json.dumps(row['value'], separators=(',', ':'), sort_keys=True) + '\n')
    # Use the exact Trade image runtime classes/lib and a JDK solely to compile the offline operator fixture.
    fixture = Path(__file__).resolve().parent / 'fixtures/trade-empty-genesis'
    image_id = subprocess.check_output(['docker', 'image', 'inspect', args.trade_image,
        '--format', '{{.Id}}'], text=True).strip()
    container = subprocess.check_output(['docker', 'create', image_id], text=True).strip()
    import tempfile
    with tempfile.TemporaryDirectory(prefix='dc-genesis-tool-') as temporary:
        tool = Path(temporary)
        try:
            subprocess.run(['docker', 'cp', f'{container}:/srv/dc/dc/TradeSvr/classes', str(tool / 'classes')], check=True)
            subprocess.run(['docker', 'cp', f'{container}:/srv/dc/dc/TradeSvr/lib', str(tool / 'lib')], check=True)
        finally:
            subprocess.run(['docker', 'rm', container], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--memory=512m', '--entrypoint', 'sh',
            '-v', f'{tool}:/tool', '-v', f'{fixture}:/fixture:ro', '-v', f'{root}:{root}',
            'eclipse-temurin:8-jdk', '-ec',
            'mkdir /tool/operator; javac -cp "/tool/classes:/tool/lib/*" -d /tool/operator /fixture/TradeEmptyGenesisBootstrap.java; '
            'exec java -Xmx192m -cp "/tool/operator:/tool/classes:/tool/lib/*" '
            'com.app.dc.service.cluster.TradeEmptyGenesisBootstrap "$1" "$2" "$3"',
            'genesis', str(root), str(args.reset_proof), str(assignment_file)], check=True)
    # Re-read after the offline install; startup stays blocked if the authoritative catalog changed.
    if zk.read_many(f'P{index:03d}' for index in range(256)) != rows:
        raise ValueError('assignment identity changed during genesis; reset again before install')
    print('FRESH_TRADE_GENESIS_PASS image=' + image_id)


if __name__ == '__main__':
    main()
