"""Bounded JDK Flight Recorder observations inside an explicitly diagnostic run."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import subprocess


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=30).strip()


def identity(node):
    row = json.loads(run('docker', 'inspect', node))[0]
    if not row['State']['Running'] or row['State']['Paused']:
        raise RuntimeError('Diagnostic voter must remain running and unpaused')
    return {key: row[key] for key in ('Id', 'RestartCount', 'Image')} | {
        'started_at': row['State']['StartedAt']}


@contextmanager
def observe(root, seconds, report):
    # Caller holds the original fresh/fault/pressure lock. This helper never
    # starts a business process, changes flags, or changes persistence policy.
    if not report.get('diagnostic_only') or not 1 <= seconds <= 600:
        raise ValueError('JFR requires an explicitly excluded, bounded diagnostic window')
    token = secrets.token_hex(6)
    work = root / ('diagnostic-jfr-' + token)
    work.mkdir(mode=0o700)
    proof = {'scope': 'PROFILED_WINDOW_EXCLUDED_FROM_PERFORMANCE_ACCEPTANCE',
             'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'STARTING',
             'maximum_seconds': seconds, 'maximum_recording_bytes_per_node': 64 * 1024 ** 2,
             'business_state_mutations': False, 'nodes': []}
    report['diagnostic_jfr'] = str(work / 'proof.json')

    def save():
        (work / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')

    save()
    active = []
    failure = None
    try:
        for kind in ('order', 'trade'):
            for slot in 'ab':
                node = root.name + '-' + kind + '-' + slot + '-hostready'
                before = identity(node)
                jvms = run('docker', 'exec', node, '/opt/java/openjdk/bin/jps', '-l').splitlines()
                pids = [line.split()[0] for line in jvms if 'sun.tools.jps.Jps' not in line]
                if len(pids) != 1:
                    raise RuntimeError('Expected one physical voter JVM for the diagnostic')
                name = 't554_' + token
                remote = '/tmp/t554-jfr-' + token
                run('docker', 'exec', node, 'mkdir', '-m', '700', remote)
                row = {'node': node, 'identity_before': before, 'pid': pids[0],
                       'name': name, 'remote': remote + '/profile.jfr'}
                proof['nodes'].append(row)
                # Track before invoking: a client timeout may still have started
                # the recording. The duration bound remains independent of us.
                active.append(row)
                row['start_output'] = run('docker', 'exec', node, '/opt/java/openjdk/bin/jcmd',
                    pids[0], 'JFR.start', 'name=' + name, 'settings=profile',
                    'duration=' + str(seconds) + 's', 'disk=true', 'maxsize=64m',
                    'filename=' + row['remote'])
                check = run('docker', 'exec', node, '/opt/java/openjdk/bin/jcmd',
                            pids[0], 'JFR.check', 'name=' + name)
                if name not in check:
                    raise RuntimeError('JFR did not confirm the exact named recording')
                save()
        proof['status'] = 'RECORDING_DIAGNOSTIC_ONLY'
        save()
        yield
    except BaseException as error:
        failure = error
        proof['failure'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        errors = []
        for row in active:
            try:
                if identity(row['node']) != row['identity_before']:
                    raise RuntimeError('Voter process changed during diagnostic recording')
                check = run('docker', 'exec', row['node'], '/opt/java/openjdk/bin/jcmd',
                            row['pid'], 'JFR.check', 'name=' + row['name'])
                if row['name'] in check:
                    row['stop_output'] = run('docker', 'exec', row['node'],
                        '/opt/java/openjdk/bin/jcmd', row['pid'], 'JFR.stop',
                        'name=' + row['name'], 'filename=' + row['remote'])
                size = int(run('docker', 'exec', row['node'], 'stat', '-c', '%s', row['remote']))
                # A final JFR chunk may slightly exceed the repository cap.
                if not 0 < size <= 80 * 1024 ** 2:
                    raise RuntimeError('Missing or unexpectedly large diagnostic recording')
                target = work / (row['node'] + '.jfr')
                run('docker', 'cp', row['node'] + ':' + row['remote'], str(target))
                target.chmod(0o600)
                row.update(file=str(target), bytes=size, sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                           identity_after=identity(row['node']))
            except BaseException as error:
                row['collection_failure'] = type(error).__name__ + ': ' + str(error)
                errors.append(row['collection_failure'])
            save()
        proof.update(status='NO_GO' if failure or errors else 'FOUR_UNCHANGED_VOTER_JFR_RECORDINGS_COLLECTED',
                     finished_at=datetime.now(timezone.utc).isoformat())
        save()
        if errors and failure is None:
            raise RuntimeError('Diagnostic recording collection failed; private evidence retained')
