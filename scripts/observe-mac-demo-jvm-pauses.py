#!/usr/bin/env python3
"""Read bounded service pause logs without attaching to or pausing any JVM."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


PAUSE = re.compile(
    r'^(?P<at>\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{4})):\s+'
    r'(?P<uptime>[\d.]+): Total time for which application threads were stopped: '
    r'(?P<seconds>\d+(?:\.\d+)?) seconds, Stopping threads took: '
    r'(?P<stopping>\d+(?:\.\d+)?) seconds\s*$')


def at(value):
    value = re.sub(r'(\.\d{6})\d+', r'\1', value.replace('Z', '+00:00'))
    value = re.sub(r'([+-]\d{2})(\d{2})$', r'\1:\2', value)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('Pause observations require explicit timezones')
    return parsed.astimezone(timezone.utc)


def parse_pause(line):
    if 'Total time for which application threads were stopped:' not in line:
        return None
    stripped = line.strip()
    match = PAUSE.fullmatch(stripped)
    outer_at = None
    extra_at = None
    if not match:
        # Concurrent HotSpot GC writers can interleave a timestamp prefix
        # immediately before a complete pause line. Accept only that exact
        # form and retain the extra timestamp; arbitrary suffixes still fail.
        prefix, separator, remainder = stripped.partition(': ')
        if separator and re.fullmatch(r'\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{4})', prefix):
            match = PAUSE.fullmatch(remainder)
            if match:
                outer_at = at(prefix).isoformat()
    if not match:
        # The other actual Java8 interleaving puts the concurrent GC
        # timestamp between a complete date+uptime prefix and the pause body.
        stamp = r'\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{4})'
        inserted = re.fullmatch(r'(' + stamp + r'):\s+(\d+(?:\.\d+)?):\s+('
                                + stamp + r'):\s+(Total time for which application threads were stopped: .+)',
                                stripped)
        if inserted:
            match = PAUSE.fullmatch(inserted[1] + ': ' + inserted[2] + ': ' + inserted[4])
            if match:
                extra_at = at(inserted[3]).isoformat()
    if not match:
        # Both concurrent writers can print a complete date+uptime header.
        # Accept only identical printed uptimes; never interpolate time.
        stamp = r'\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{4})'
        doubled = re.fullmatch(r'(?P<first>' + stamp + r'):\s+(?:(?P<before>' + stamp
            + r'):\s+)?(?P<uptime>\d+(?:\.\d+)?):\s+(?:(?P<after>' + stamp
            + r'):\s+)?(?P<duplicate>\d+(?:\.\d+)?):\s+'
            r'(?P<body>Total time for which application threads were stopped: .+)', stripped)
        if (doubled and bool(doubled['before']) != bool(doubled['after'])
                and doubled['uptime'] == doubled['duplicate']):
            match = PAUSE.fullmatch((doubled['before'] or doubled['first']) + ': '
                                   + doubled['uptime'] + ': ' + doubled['body'])
            if match:
                outer_at = at(doubled['first']).isoformat() if doubled['before'] else None
                extra_at = at(doubled['after']).isoformat() if doubled['after'] else None
    if not match:
        raise ValueError('Unrecognized application-pause record; cannot infer zero pauses')
    fields = match.groupdict()
    result = {'at': at(fields['at']).isoformat(), 'uptime_seconds': float(fields['uptime']),
            'stopped_ms': round(float(fields['seconds']) * 1000, 7),
            'stopping_threads_ms': round(float(fields['stopping']) * 1000, 7)}
    if outer_at is not None:
        result['interleaved_outer_timestamp'] = outer_at
    if extra_at is not None:
        result['interleaved_extra_timestamp'] = extra_at
    return result


def parse_log_pauses(lines, file):
    """Recover only a directly adjacent, identical-uptime interleaved prefix."""
    previous = ''
    events = []
    for number, line in enumerate(lines, 1):
        try:
            event = parse_pause(line)
        except ValueError:
            missing = re.match(r'^(\d+(?:\.\d+)?): Total time for which application threads were stopped:',
                               line.strip())
            stamp = r'\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{4})'
            anchor = re.match(r'^(?:(?P<outer>' + stamp + r'):\s+)?(?P<at>' + stamp + r'):\s+'
                              r'(?P<uptime>\d+(?:\.\d+)?):\s+\S', previous.strip())
            if not missing or not anchor or missing[1] != anchor['uptime']:
                raise
            # Do not infer wall time from process start or interpolate uptime.
            # The preceding complete prefix has this exact printed uptime;
            # parse_pause still validates the entire original pause record.
            event = parse_pause(anchor['at'] + ': ' + line.strip())
            event['interleaved_timestamp_prefix_line'] = number - 1
            event['interleaved_timestamp_prefix'] = anchor[0]
            if anchor['outer']:
                event['interleaved_outer_timestamp'] = at(anchor['outer']).isoformat()
        if event:
            events.append(dict(event, file=file, line=number))
        previous = line
    return events


def summarize(events, since, until):
    selected = [e for e in events if since <= at(e['at']) < until]
    values = sorted(e['stopped_ms'] for e in selected)
    return {'events_logged_in_window': len(selected),
            'max_logged_stop_ms': max(values) if values else None,
            'p99_logged_stop_ms': values[math.ceil(len(values) * .99) - 1] if values else None,
            'reported_stop_ms_sum': round(sum(values), 7),
            'logged_stops_over_3000ms': [e for e in selected if e['stopped_ms'] > 3000],
            'scope': 'Completed pauses whose log timestamp falls in this window; '
                     'not request latency, elapsed window downtime, or proof about a pause still in progress.'}


def read(*args):
    return subprocess.check_output(list(args), text=True, stderr=subprocess.PIPE, timeout=30)


def identity(node):
    return {'id': node['Id'], 'started_at': node['State']['StartedAt'],
            'restart_count': node['RestartCount'], 'running': node['State']['Running']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--since', required=True)
    parser.add_argument('--until', required=True)
    args = parser.parse_args()
    root = args.run.resolve(strict=True)
    since, until = at(args.since), at(args.until)
    if since >= until or not re.fullmatch(r'mac-demo-\d{8}-\d{6}', root.name):
        parser.error('Expected an existing Demo generation and a positive observation window')
    os.umask(0o077)
    if read('docker', 'context', 'show').strip() != 'colima':
        raise RuntimeError('Expected the original Colima context')
    work = Path(tempfile.mkdtemp(prefix='jvm-pauses-', dir=root))
    proof = work / 'proof.json'
    report = {'status': 'READING_SERVICE_LOGS_NO_JVM_ATTACH', 'since': since.isoformat(),
              'until': until.isoformat(), 'work': str(work), 'nodes': [],
              'application_mutations': False, 'jvm_attach_or_thread_dump': False}

    def save():
        proof.write_text(json.dumps(report, indent=2) + '\n')

    save()
    names = [root.name + '-' + kind + '-' + slot + '-hostready'
             for kind in ('order', 'trade') for slot in 'ab']
    try:
        before = json.loads(read('docker', 'inspect', *names))
        for node in before:
            name = node['Name'][1:]
            if (not node['State']['Running'] or node['State']['Paused']
                    or at(node['State']['StartedAt']) > since
                    or node['Config']['Labels'].get('otc.mac.demo.generation') != root.name):
                raise RuntimeError('A voter changed or was unavailable during the selected window')
            extra = dict(x.split('=', 1) for x in node['Config']['Env']).get('EXTRA_JAVA_OPTS', '')
            if ('-Xloggc:/srv/dc/log/jvm-gc.log' not in extra
                    or '-XX:+PrintGCApplicationStoppedTime' not in extra):
                raise RuntimeError('The service pause observer is not enabled on ' + name)
            listing = read('docker', 'exec', name, 'find', '/srv/dc/log', '-maxdepth', '1',
                           '-type', 'f', '-name', 'jvm-gc.log*', '-printf', '%f\t%s\n')
            files = [line.split('\t') for line in listing.splitlines()]
            if (not 1 <= len(files) <= 6 or any(
                    not re.fullmatch(r'jvm-gc\.log(?:\.[0-9]+(?:\.current)?)?', file)
                    or not 0 <= int(size) <= 12 * 1024 ** 2 for file, size in files)):
                raise RuntimeError('Unexpected or unbounded service pause logs')
            if shutil.disk_usage(root).free < sum(int(size) for _, size in files) + 512 * 1024 ** 2:
                raise RuntimeError('Insufficient storage for a bounded private log observation')
            events = []
            row = {'name': name, 'identity': identity(node), 'files': []}
            report['nodes'].append(row)
            for file, size in sorted(files):
                target = work / (name + '-' + file + '.gz')
                raw_hash, received = hashlib.sha256(), 0
                with (work / (name + '-' + file + '.capture.log')).open('x') as log:
                    process = subprocess.Popen(['docker', 'exec', name, 'timeout', '30',
                                                'cat', '/srv/dc/log/' + file],
                                               stdout=subprocess.PIPE, stderr=log)
                    try:
                        with gzip.open(target, 'wb', compresslevel=1) as sink:
                            for block in iter(lambda: process.stdout.read(65536), b''):
                                received += len(block)
                                if received > 12 * 1024 ** 2:
                                    raise RuntimeError('Pause log exceeded its bounded capture')
                                raw_hash.update(block)
                                sink.write(block)
                        if process.wait(timeout=30):
                            raise RuntimeError('Pause log read failed')
                    finally:
                        if process.poll() is None:
                            process.terminate()
                            process.wait(timeout=10)
                with gzip.open(target, 'rt', errors='strict') as captured:
                    events.extend(parse_log_pauses(captured, file))
                row['files'].append({'name': file, 'bytes_at_listing': int(size),
                                     'captured_bytes': received, 'raw_sha256': raw_hash.hexdigest()})
                save()
            row['summary'] = summarize(events, since, until)
            row['events'] = events
            save()
        after = json.loads(read('docker', 'inspect', *names))
        if [identity(n) for n in before] != [identity(n) for n in after]:
            raise RuntimeError('Voter lifecycle changed during pause-log capture')
        report['status'] = 'FOUR_SERVICE_JVM_PAUSE_LOGS_OBSERVED_WITHOUT_ATTACH'
        save()
    except BaseException as error:
        report.update(status='NO_GO_INCOMPLETE_PAUSE_OBSERVATION', failure_type=type(error).__name__)
        save()
        raise
    print(report['status'], proof)


if __name__ == '__main__':
    main()
