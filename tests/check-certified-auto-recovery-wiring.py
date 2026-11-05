#!/usr/bin/env python3
"""Read-only fail-closed preflight for the REAL Order/Trade Common auto-HA beans.

A passing Spring compilation or nonempty Snapshot test cannot prove that an
application can start its default full automatic HA graph. This preflight only
checks the production bean declarations and same Common JAR evidence; it
NEVER claims ready/failover success (which requires real ZooKeeper/Netty).
"""
import argparse
import hashlib
from pathlib import Path
import re
import sys

PRODUCTION_BEANS = {
    'OrderSvr': ('order', 'orderCommonCertifiedPhysicalRecovery'),
    'TradeSvr': ('trade', 'tradeCommonCertifiedPhysicalRecovery'),
}


def without_comments(source):
    # Keep the @Bean signature parse robust against commented-out examples.
    source = re.sub(r'/\*.*?\*/', '', source, flags=re.S)
    return re.sub(r'(?m)//[^\n]*', '', source)


def check_service(name, root, bean):
    folder = root / 'src/main/java/com/app/dc/service/state'
    if not folder.is_dir():
        return False, f'{name}:SOURCE_NOT_FOUND:{folder}'
    candidates = []
    for file in sorted(folder.rglob('*.java')):
        source = without_comments(file.read_text(encoding='utf-8'))
        if bean not in source:
            continue
        # @Qualifier consumption is not a producer. Require explicit bean
        # definition + exact Common API return type on a real method.
        pattern = r'@Bean\s*\(\s*name\s*=\s*"' + re.escape(bean) + r'"\s*\)\s*' \
                  r'(?:@[A-Za-z_][\w.]*\s*(?:\([^)]*\))?\s*)*' \
                  r'public\s+[\w$.<>?,\s]*?DurablePhysicalRecovery\s+\w+\s*\('
        if re.search(pattern, source):
            candidates.append(file.relative_to(root).as_posix())
    if len(candidates) != 1:
        return False, f'{name}:PHYSICAL_RECOVERY_BEAN_MISSING_OR_DUPLICATE:name={bean} producers={len(candidates)}'
    return True, f'{name}:PHYSICAL_RECOVERY_BEAN_DECLARED:{candidates[0]}'


def digest(file):
    h = hashlib.sha256()
    with file.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--order-root', type=Path, default=Path('.work/t444-order-stream'))
    p.add_argument('--trade-root', type=Path, default=Path('.work/t452-trade-windowed-e2'))
    p.add_argument('--order-common-jar', type=Path)
    p.add_argument('--trade-common-jar', type=Path)
    args = p.parse_args()
    checked = []
    for service, (arg, bean) in PRODUCTION_BEANS.items():
        result = check_service(service, getattr(args, arg + '_root'), bean)
        checked.append(result)
        print(('PASS' if result[0] else 'NO-GO') + ':T489_' + result[1])
    if bool(args.order_common_jar) != bool(args.trade_common_jar):
        checked.append((False, 'both exact Common JAR paths required'))
        print('NO-GO:T489_BOTH_SERVICE_COMMON_JARS_REQUIRED')
    elif args.order_common_jar:
        if not args.order_common_jar.is_file() or not args.trade_common_jar.is_file():
            checked.append((False, 'missing jar'))
            print('NO-GO:T489_MISSING_COMMON_JAR')
        else:
            a, b = digest(args.order_common_jar), digest(args.trade_common_jar)
            print(('PASS' if a == b else 'NO-GO') + ':T489_ORDER_TRADE_COMMON_JAR_SHA256:' + a + ':' + b)
            checked.append((a == b, 'same Common JAR'))
    if not all(success for success, _ in checked):
        print('NO-GO:T489_PRODUCTION_AUTOMATIC_HA_NOT_AUTHORIZED')
        return 2
    print('PASS:T489_BEAN_STRUCTURE_ONLY_REAL_HA_STILL_REQUIRES_RUNTIME_VERIFICATION')
    return 0


if __name__ == '__main__':
    sys.exit(main())
