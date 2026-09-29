#!/usr/bin/env python3
"""Cap fresh disposable-test application file logs before business containers start."""
import argparse
from pathlib import Path
import subprocess

NODES = ('GW', 'LoginSvr', 'MDSvr', 'MDSvrA', 'MDSvrB', 'MDSvrC', 'APSSvr',
         'OrderSvr', 'OrderSvrA', 'OrderSvrB', 'OrderSvrC', 'TradeSvr', 'TradeSvrA', 'TradeSvrB',
         'LiqSvr', 'ManagerSvr', 'AdminSvr', 'RobotSvr', 'ProjectionSvr')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', required=True, type=Path)
    parser.add_argument('--reload-running', action='store_true',
                        help='update logging-only config watched by running test services')
    args = parser.parse_args()
    root = args.runtime_root
    if str(root) not in {'/data/dc-saas-runtime', '/opt/dc-saas-runtime'} or root.resolve() != root:
        raise ValueError('unexpected test runtime root')
    running = subprocess.check_output(['docker', 'ps', '--format', '{{.Names}}'], text=True).split()
    infra = {'dc-saas-mysql', 'dc-saas-zookeeper', 'dc-saas-clickhouse'}
    if not args.reload_running and any(name.startswith('dc-saas-') and name not in infra for name in running):
        raise ValueError('configure fresh logs before starting business services')
    for node in NODES:
        path = root / f'control/overrides/{node}/config/log4j.ini'
        if path.is_symlink() or path.parent.resolve() != path.parent:
            raise ValueError('linked logging config refused')
        if path.exists():
            content = path.read_text().replace('org.apache.log4j.DailyRollingFileAppender',
                                              'org.apache.log4j.RollingFileAppender')
            lines = [line for line in content.splitlines() if not line.startswith(
                ('log4j.appender.file.MaxFileSize=', 'log4j.appender.file.MaxBackupIndex='))]
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            lines = ['log4j.rootLogger=INFO,file,stdout',
                'log4j.logger.com.gateway.connector.tcp.client.GateWayApi=ERROR',
                'log4j.logger.com.gw.common.utils=WARN',
                'log4j.appender.file=org.apache.log4j.RollingFileAppender',
                f'log4j.appender.file.File=../../log/{node}.log', 'log4j.appender.file.Append=true',
                'log4j.appender.file.layout=org.apache.log4j.PatternLayout',
                'log4j.appender.file.layout.ConversionPattern=%d{yyyy/MM/dd HH:mm:ss.SSS} %p %m (%C{1}:%L)%n',
                'log4j.appender.stdout=org.apache.log4j.ConsoleAppender',
                'log4j.appender.stdout.layout=org.apache.log4j.PatternLayout',
                'log4j.appender.stdout.layout.ConversionPattern=%d{yyyy/MM/dd HH:mm:ss.SSS} %p %m (%C{1}:%L)%n']
        lines += ['log4j.appender.file.MaxFileSize=16MB', 'log4j.appender.file.MaxBackupIndex=3']
        path.write_text('\n'.join(lines) + '\n')
        path.chmod(0o600)
    print('BOUNDED_TEST_LOGS_PASS nodes=19 perNodeApproxMiB=64')


if __name__ == '__main__':
    main()
