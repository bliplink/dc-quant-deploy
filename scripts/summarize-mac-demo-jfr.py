#!/usr/bin/env python3
"""Summarize retained JFR events inside one explicitly excluded TCP window."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import xml.etree.ElementTree as ET


EVENTS = ('jdk.ExecutionSample', 'jdk.NativeMethodSample', 'jdk.JavaMonitorEnter',
          'jdk.ThreadPark', 'jdk.FileRead', 'jdk.FileWrite', 'jdk.SocketRead',
          'jdk.SocketWrite', 'jdk.GarbageCollection', 'jdk.GCPhasePause', 'jdk.DataLoss')


def at(value):
    parsed = datetime.fromisoformat(re.sub(r'(\.\d{6})\d+', r'\1', value.replace('Z', '+00:00')))
    if parsed.tzinfo is None:
        raise ValueError('JFR event requires an explicit timezone')
    return parsed.astimezone(timezone.utc)


def duration(value):
    found = re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?', value)
    if not found:
        raise ValueError('Unknown JFR duration')
    hours, minutes, seconds = (float(x or 0) for x in found.groups())
    return hours * 3600 + minutes * 60 + seconds


def value(element, name):
    return element.findtext("./value[@name='" + name + "']")


def frames(event):
    result = []
    for frame in event.findall("./struct[@name='stackTrace']/array[@name='frames']/struct"):
        method = frame.find("./struct[@name='method']")
        if method is not None:
            owner = method.find("./struct[@name='type']")
            if owner is not None and value(owner, 'name') and value(method, 'name'):
                result.append(value(owner, 'name').replace('/', '.') + '.' + value(method, 'name'))
    return result


class BoundedXml:
    def __init__(self, stream):
        self.stream, self.size = stream, 0

    def read(self, size=-1):
        data = self.stream.read(size)
        self.size += len(data)
        if self.size > 512 * 1024 ** 2:
            raise RuntimeError('JFR XML exceeded the bounded read budget')
        return data


def summarize(stream, since, until):
    counts, leaves, callers = Counter(), defaultdict(Counter), defaultdict(Counter)
    waits = defaultdict(lambda: {'count': 0, 'overlap_ms_sum': 0.0, 'max_event_ms': 0.0})
    seen, lost_events, lost_bytes = 0, 0, 0
    for _, event in ET.iterparse(BoundedXml(stream), events=('end',)):
        if event.tag != 'event':
            continue
        kind = event.attrib['type']
        if kind not in EVENTS:
            event.clear()
            continue
        seen += 1
        if seen > 200000:
            raise RuntimeError('JFR event count exceeded the bounded read budget')
        if kind == 'jdk.DataLoss':
            lost_events += 1
            lost_bytes += int(value(event, 'amount') or 0)
        start = at(value(event, 'startTime'))
        elapsed = duration(value(event, 'duration') or 'PT0S')
        overlap = max(0.0, (min(until, start + timedelta(seconds=elapsed)) - max(since, start)).total_seconds())
        sample = kind in ('jdk.ExecutionSample', 'jdk.NativeMethodSample')
        if not (since <= start < until if sample or elapsed == 0 else overlap > 0):
            event.clear()
            continue
        counts[kind] += 1
        stack = frames(event)
        leaf = stack[0] if stack else 'NO_RECORDED_STACK'
        caller = next((x for x in stack if x.startswith(('com.app.common.', 'com.app.dc.'))), leaf)
        leaves[kind][leaf] += 1
        callers[kind][caller] += 1
        if not sample:
            path = value(event, 'path') or ''
            category = ('APPLICATION_LOG' if '/log/' in path else 'WAL' if path.endswith('.wal')
                        else 'COMMIT_METADATA' if any(x in path for x in ('commit', '.pending'))
                        else 'OTHER_FILE_OR_STDIO') if kind.startswith('jdk.File') else ''
            row = waits[(kind, category, caller)]
            row['count'] += 1
            row['overlap_ms_sum'] += overlap * 1000
            row['max_event_ms'] = max(row['max_event_ms'], elapsed * 1000)
        event.clear()
    return {'events_read': seen, 'data_loss_events_in_recording': lost_events,
            'reported_data_loss_bytes_in_recording': lost_bytes,
            'events_overlapping_window': dict(counts),
            'sampled_leaf_methods': {key: val.most_common(24) for key, val in leaves.items()},
            'first_recorded_application_callers': {key: val.most_common(24) for key, val in callers.items()},
            'long_events_by_application_caller': [dict(event_type=k[0], file_category=k[1], caller=k[2],
                **{field: round(x, 6) if isinstance(x, float) else x for field, x in row.items()})
                for k, row in sorted(waits.items(), key=lambda x: x[1]['overlap_ms_sum'], reverse=True)[:60]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('measurement', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    if args.output.exists():
        parser.error('Use a new summary output; preserve earlier evidence')
    measurement = json.loads(args.measurement.read_text())
    if not measurement.get('diagnostic_only') or not measurement.get('diagnostic_jfr'):
        parser.error('Only an explicitly excluded profiled measurement is supported')
    proof = json.loads(Path(measurement['diagnostic_jfr']).read_text())
    if proof['status'] != 'FOUR_UNCHANGED_VOTER_JFR_RECORDINGS_COLLECTED' or len(proof['nodes']) != 4:
        raise RuntimeError('Incomplete or changed-voter diagnostic recording')
    since = datetime.fromtimestamp(measurement['scheduled_start_epoch_ms'] / 1000, timezone.utc)
    until = since + timedelta(seconds=measurement['target_seconds'])
    java = Path(subprocess.check_output(['/usr/libexec/java_home', '-v', '1.8'], text=True).strip())
    report = {'scope': 'DIAGNOSTIC_SAMPLED_METHODS_AND_THRESHOLD_EVENTS_NOT_REQUEST_LATENCY',
              'measurement': str(args.measurement.resolve()), 'since': since.isoformat(), 'until': until.isoformat(),
              'sampling_and_threshold_caveat': 'Samples are not exact CPU attribution; long-event totals can overlap '
                  'across threads and omit events below the JDK profile thresholds. GC duration is not total safepoint time.',
              'measurement_sha256': hashlib.sha256(args.measurement.read_bytes()).hexdigest(), 'nodes': []}
    for row in proof['nodes']:
        path = Path(row['file'])
        if (row['identity_before'] != row['identity_after'] or not 0 < path.stat().st_size <= 80 * 1024 ** 2
                or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']):
            raise RuntimeError('Retained JFR source differs from its exact recorded voter')
        with subprocess.Popen([str(java / 'bin/jfr'), '-J-Xmx96m', 'print', '--xml', '--stack-depth', '24',
                               '--events', ','.join(EVENTS), str(path)], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL) as child:
            deadline = threading.Timer(90, child.kill)
            deadline.daemon = True
            deadline.start()
            try:
                result = summarize(child.stdout, since, until)
            except BaseException:
                child.kill()
                raise
            finally:
                deadline.cancel()
            if child.wait(timeout=30) != 0:
                raise RuntimeError('JDK reader failed; summary is incomplete')
        report['nodes'].append({'node': row['node'], 'jfr_sha256': row['sha256'], **result})
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print('DIAGNOSTIC_JFR_WINDOW_SUMMARIZED', args.output)


if __name__ == '__main__':
    main()
