#!/usr/bin/env python3
"""Read-only evidence census for T522 E2 bootstrap. NEVER authorizes HA or trading."""
import argparse
import re
import subprocess
import sys

ROOT = '/otc/t522-fresh-20261106-r1'
ZK = 'otc-t84-source-integrated-otc-ha-zk1-1'
PARTITION = re.compile(r'^P([0-9]{3})\|2\|([A-Za-z0-9_.-]+)\|([A-Za-z0-9_.-]+)\|STRICT_QUORUM\|READY$')

def run(argv, *, stdin=None, timeout=35):
    result = subprocess.run(argv, input=stdin, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError('COMMAND_FAILED: ' + ' '.join(argv[:3]) +
                           ' exit=' + str(result.returncode))
    return result.stdout

def manifest(service, short):
    raw = run(['docker', 'exec', '-i', ZK, 'zkCli.sh', '-server',
               '127.0.0.1:2181'],
              stdin='get ' + ROOT + '/' + short + '/manifest\nquit\n')
    lines = [line.strip() for line in raw.splitlines()]
    if 'NPC1|2' not in lines:
        raise RuntimeError(short + ':NO_AUTHENTICATED_E2_MANIFEST')
    found = {}
    for line in lines:
        m = PARTITION.fullmatch(line)
        if m:
            if m.group(1) in found:
                raise RuntimeError(short + ':DUPLICATE_P' + m.group(1))
            found[m.group(1)] = m
    if len(found) != 256:
        raise RuntimeError(short + ':NOT_EXACT_256_E2_READY:' + str(len(found)))
    for i in range(256):
        part = '%03d' % i
        m = found.get(part)
        if m is None:
            raise RuntimeError(short + ':MISSING_P' + part)
        a, b = service + 'A', service + 'B'
        expected = (a, b) if i < 128 else (b, a)
        if (m.group(2), m.group(3)) != expected:
            raise RuntimeError(short + ':ROLE_MISMATCH_P' + part)
    print('PASS:T522_E2_READY_MANIFEST_STRUCTURE_ONLY service=' + service +
          ' partitions=256; not RSA re-verification')

def node(service, short, letter):
    name = 'otc-t522-' + short + '-' + letter.lower() + '-hostready-r2'
    status = run(['docker', 'inspect', name, '--format', '{{.State.Running}}']).strip()
    if status != 'true':
        raise RuntimeError(name + ':DOCKER_NOT_RUNNING')
    logs = run(['docker', 'logs', name])
    if 'Started ' + service + ' in ' not in logs:
        raise RuntimeError(name + ':SPRING_START_MISSING')
    if 'COMMON_ONLY_CERTIFIED_BUSINESS_SPRING_NO_LEGACY_ZK_START' not in logs:
        raise RuntimeError(name + ':COMMON_ONLY_START_MISSING')
    if short == 'order' and 'TradeSvr partition primaries preconnected: 2/2' not in logs:
        raise RuntimeError(name + ':TRADE_TCP_PAIR_NOT_CONNECTED')
    base = '/srv/dc/data/t522-ready-v1/' + service + '/' + service + letter
    count = run(['docker', 'exec', name, 'sh', '-c',
                 'find "' + base + '" -type f -name business.wal | wc -l']).strip()
    if not count.isdigit() or int(count) != 256:
        raise RuntimeError(name + ':PHYSICAL_WAL_COUNT:' + count)
    print('PASS:T522_E2_SPRING_AND_WAL service=' + service + ' node=' + letter +
          ' wal=256; no customer ACK proof')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        for service, short in [('OrderSvr', 'order'), ('TradeSvr', 'trade')]:
            manifest(service, short)
            for letter in 'AB':
                node(service, short, letter)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print('NO-GO:T522_E2_RUNTIME_PREFLIGHT:' + str(error))
        return 2
    print('PASS:T522_E2_BOOTSTRAP_RUNTIME_ONLY; NO-GO:AUTO_HA_AND_REAL_TRADING_UNPROVEN')
    return 0

if __name__ == '__main__':
    sys.exit(main())