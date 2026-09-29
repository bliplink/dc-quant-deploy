#!/usr/bin/env python3
"""Exclude configured SaaS listeners from Linux's outbound ephemeral allocation."""
import argparse
import os
from pathlib import Path
import subprocess
import sys


def parse_ports(value):
    ports = set()
    for part in value.strip().split(','):
        if not part:
            continue
        bounds = part.split('-')
        if len(bounds) > 2 or any(not item.isdigit() for item in bounds):
            raise ValueError('invalid reserved-port list')
        first, last = int(bounds[0]), int(bounds[-1])
        if not 1 <= first <= last <= 65535:
            raise ValueError('invalid port range')
        ports.update(range(first, last + 1))
    return ports


def format_ports(ports):
    ranges = []
    for port in sorted(ports):
        if ranges and ranges[-1][1] + 1 == port:
            ranges[-1][1] = port
        else:
            ranges.append([port, port])
    return ','.join(str(first) if first == last else f'{first}-{last}' for first, last in ranges)


def service_ports(env):
    # Include optional nodes too: enabling a cluster later must not collide.
    ports = {18090, 18092}
    for key, value in env.items():
        if key.endswith('_PORT') and key.startswith(('MYSQL_', 'CLICKHOUSE_', 'ZOOKEEPER_',
                'GW_', 'LOGINSVR_', 'MDSVR_', 'APSSVR_', 'ORDERSVR_', 'TRADESVR_',
                'LIQSVR_', 'MANAGERSVR_', 'ADMINSVR_', 'PROJECTIONSVR_', 'WEB_')):
            if not value.isdigit() or not 1 <= int(value) <= 65535:
                raise ValueError(f'invalid configured port: {key}')
            ports.add(int(value))
    return ports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'linux' or (args.apply and os.geteuid() != 0):
        parser.error('requires Linux Docker host; --apply requires root')
    desired = service_ports(os.environ)
    current = parse_ports(subprocess.check_output(
        ['sysctl', '-n', 'net.ipv4.ip_local_reserved_ports'], text=True))
    target = Path('/etc/sysctl.d/90-dc-saas-service-ports.conf')
    if target.is_symlink():
        raise ValueError('refusing symlink sysctl configuration')
    if target.exists():
        for line in target.read_text().splitlines():
            if line.startswith('net.ipv4.ip_local_reserved_ports='):
                current.update(parse_ports(line.split('=', 1)[1]))
    merged = format_ports(current | desired)
    if args.apply:
        # Preserve reservations made by other applications; never clear them.
        subprocess.run(['sysctl', '-w', 'net.ipv4.ip_local_reserved_ports=' + merged],
                       check=True, stdout=subprocess.DEVNULL)
        actual = parse_ports(subprocess.check_output(
            ['sysctl', '-n', 'net.ipv4.ip_local_reserved_ports'], text=True))
        if not (current | desired) <= actual:
            raise RuntimeError('reserved-port verification failed')
        target.write_text('# SaaS listeners plus preserved host reservations\n'
                          'net.ipv4.ip_local_reserved_ports=' + merged + '\n')
    print(f'PORT_RESERVATION_{"PASS" if args.apply else "PLAN"} ports={merged}')


if __name__ == '__main__':
    main()
