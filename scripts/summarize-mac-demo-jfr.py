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
import tempfile
import threading


EVENTS = ('jdk.ExecutionSample', 'jdk.NativeMethodSample', 'jdk.JavaMonitorEnter', 'jdk.JavaMonitorWait',
          'jdk.ThreadPark', 'jdk.FileRead', 'jdk.FileWrite', 'jdk.SocketRead',
          'jdk.SocketWrite', 'jdk.GarbageCollection', 'jdk.GCPhasePause', 'jdk.DataLoss')


def at(value):
    parsed = datetime.fromisoformat(re.sub(r'(\.\d{6})\d+', r'\1', value.replace('Z', '+00:00')))
    if parsed.tzinfo is None:
        raise ValueError('JFR event requires an explicit timezone')
    return parsed.astimezone(timezone.utc)


def summarize(stream, since, until):
    counts, leaves, callers = Counter(), defaultdict(Counter), defaultdict(Counter)
    waits = defaultdict(lambda: {'count': 0, 'overlap_ms_sum': 0.0, 'max_event_ms': 0.0})
    paths = defaultdict(Counter)
    file_io = defaultdict(lambda: {'count': 0, 'bytes': 0, 'threads': set(), 'header_size_reads': 0})
    seen, lost_events, lost_bytes, read_bytes = 0, 0, 0, 0
    if stream.readline(8193) != b'T554_JFR_COMPACT_V2\n':
        raise RuntimeError('Missing bounded JDK consumer header; inspect retained reader stderr')
    original_events = None
    while True:
        raw = stream.readline(8193)
        read_bytes += len(raw)
        if not raw or len(raw) > 8192 or read_bytes > 128 * 1024 ** 2:
            raise RuntimeError('Missing completion marker or exceeded compact JFR read budget')
        fields = raw.decode('utf-8').rstrip('\n').split('\t')
        if fields[0] == 'END':
            if len(fields) != 3 or int(fields[2]) != seen or stream.read(1):
                raise RuntimeError('Incomplete or trailing compact JFR events')
            original_events = int(fields[1])
            break
        if len(fields) != 10 or fields[0] not in EVENTS or int(fields[2]) < 0 or int(fields[6]) < 0:
            raise RuntimeError('Invalid bounded JFR event')
        kind, timestamp, nanos, leaf, caller, category, lost, byte_count, thread_id, application_path = fields
        seen += 1
        if seen > 200000:
            raise RuntimeError('JFR event count exceeded the bounded read budget')
        if kind == 'jdk.DataLoss':
            lost_events += 1
            lost_bytes += int(lost)
        start = at(timestamp)
        elapsed = int(nanos) / 1e9
        overlap = max(0.0, (min(until, start + timedelta(seconds=elapsed)) - max(since, start)).total_seconds())
        sample = kind in ('jdk.ExecutionSample', 'jdk.NativeMethodSample')
        if not (since <= start < until if sample or elapsed == 0 else overlap > 0):
            continue
        counts[kind] += 1
        leaves[kind][leaf] += 1
        callers[kind][caller] += 1
        paths[kind][application_path] += 1
        if kind.startswith('jdk.File'):
            io = file_io[(kind, category, application_path)]
            io['count'] += 1
            io['bytes'] += int(byte_count)
            io['threads'].add(int(thread_id))
            io['header_size_reads'] += kind == 'jdk.FileRead' and int(byte_count) == 28
        if not sample:
            row = waits[(kind, category, caller)]
            row['count'] += 1
            row['overlap_ms_sum'] += overlap * 1000
            row['max_event_ms'] = max(row['max_event_ms'], elapsed * 1000)
    return {'events_read': seen, 'original_recorded_events_read': original_events,
            'data_loss_events_in_recording': lost_events,
            'reported_data_loss_bytes_in_recording': lost_bytes,
            'events_overlapping_window': dict(counts),
            'sampled_leaf_methods': {key: val.most_common(24) for key, val in leaves.items()},
            'first_recorded_application_callers': {key: val.most_common(24) for key, val in callers.items()},
            'recorded_application_paths': {key: val.most_common(24) for key, val in paths.items()},
            'file_io_by_application_path': [dict(event_type=k[0], file_category=k[1], application_path=k[2],
                count=row['count'], bytes=row['bytes'], header_size_reads=row['header_size_reads'],
                unique_threads=len(row['threads'])) for k, row in sorted(file_io.items(),
                key=lambda x: x[1]['count'], reverse=True)[:30]],
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
    reader_source = Path(__file__).resolve().parents[1] / 'tests/fixtures/performance/T554JfrCompactReader.java'
    work = Path(tempfile.mkdtemp(prefix='compact-reader-', dir=args.output.parent))
    jfr_jar = java / 'jre/lib/jfr.jar'
    subprocess.run([str(java / 'bin/javac'), '-cp', str(jfr_jar), '-d', str(work), str(reader_source)],
                   check=True, timeout=30)
    report = {'scope': 'DIAGNOSTIC_SAMPLED_METHODS_AND_THRESHOLD_EVENTS_NOT_REQUEST_LATENCY',
              'measurement': str(args.measurement.resolve()), 'since': since.isoformat(), 'until': until.isoformat(),
              'sampling_and_threshold_caveat': 'Samples are not exact CPU attribution; long-event totals can overlap '
                  'across threads and omit events below the JDK profile thresholds. GC duration is not total safepoint time.',
              'measurement_sha256': hashlib.sha256(args.measurement.read_bytes()).hexdigest(),
              'reader_source_sha256': hashlib.sha256(reader_source.read_bytes()).hexdigest(),
              'reader_class_sha256': hashlib.sha256((work / 'T554JfrCompactReader.class').read_bytes()).hexdigest(),
              'reader_max_heap_mib': 192, 'nodes': []}
    for row in proof['nodes']:
        path = Path(row['file'])
        if (row['identity_before'] != row['identity_after'] or not 0 < path.stat().st_size <= 80 * 1024 ** 2
                or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']):
            raise RuntimeError('Retained JFR source differs from its exact recorded voter')
        error_path = work / (row['node'] + '.stderr')
        with error_path.open('xb') as error_log, subprocess.Popen(
                [str(java / 'bin/java'), '-Xms16m', '-Xmx192m', '-XX:+UseSerialGC', '-cp',
                 str(work) + os.pathsep + str(jfr_jar), 'T554JfrCompactReader', str(path),
                 str(measurement['scheduled_start_epoch_ms']),
                 str(measurement['scheduled_start_epoch_ms'] + measurement['target_seconds'] * 1000)],
                stdout=subprocess.PIPE, stderr=error_log) as child:
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
                raise RuntimeError('JDK reader failed; summary is incomplete; stderr retained at ' + str(error_path))
        report['nodes'].append({'node': row['node'], 'jfr_sha256': row['sha256'], **result})
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print('DIAGNOSTIC_JFR_WINDOW_SUMMARIZED', args.output)


if __name__ == '__main__':
    main()
