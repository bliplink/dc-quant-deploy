"""Prepare and run the deployed GateWayApi as a bounded native TCP test client."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from datetime import datetime, timezone


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'tests/MacDemoNativeTcpLoad.java'
# The generator shares the Mac's RAM with Colima. Keep its retained results
# and Netty arenas bounded rather than perturbing the service VM through
# host memory compression. These options never enter a business JVM.
CLIENT_JVM_ARGS = ['-Xms32m', '-Xmx96m', '-XX:+UseSerialGC',
                   '-Dio.netty.allocator.numHeapArenas=1',
                   '-Dio.netty.allocator.numDirectArenas=1',
                   '-Dio.netty.allocator.maxOrder=8']


def prepare(root, source=SOURCE, class_name='MacDemoNativeTcpLoad'):
    if source.stem != class_name or not class_name.isidentifier():
        raise ValueError('Native client source and Java class must match')
    image = subprocess.check_output(['docker', 'inspect', '-f', '{{.Image}}', 'dc-saas-robotsvr'], text=True).strip()
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    profile_hash = hashlib.sha256(json.dumps(CLIENT_JVM_ARGS).encode()).hexdigest()
    work = root / ('native-tcp-client-' + source_hash[:12] + '-' + image.split(':')[-1][:12] + '-' + profile_hash[:8])
    identity = work / 'identity.json'
    if identity.exists():
        recorded = json.loads(identity.read_text())
        if recorded.get('client_jvm_args') != CLIENT_JVM_ARGS:
            raise RuntimeError('Prepared native client memory/GC profile differs')
        if recorded['robot_image'] != image:
            raise RuntimeError('Native client dependency image differs from its preparation')
        for name, expected in recorded['dependencies'].items():
            if hashlib.sha256((work / 'lib' / name).read_bytes()).hexdigest() != expected:
                raise RuntimeError('Prepared native client dependency bytes changed')
        for name, expected in recorded['classes'].items():
            if hashlib.sha256((work / name).read_bytes()).hexdigest() != expected:
                raise RuntimeError('Prepared native client class bytes changed')
        return work
    work.mkdir(mode=0o700)
    subprocess.run(['docker', 'cp', 'dc-saas-robotsvr:/srv/dc/dc/RobotSvr/lib', str(work / 'lib')], check=True,
                   stdout=subprocess.DEVNULL)
    java_home = subprocess.check_output(['/usr/libexec/java_home', '-v', '1.8'], text=True).strip()
    subprocess.run([java_home + '/bin/javac', '-cp', str(work / 'lib' / '*'), '-d', str(work), str(source)], check=True)
    dependencies = {jar.name: hashlib.sha256(jar.read_bytes()).hexdigest() for jar in sorted((work / 'lib').glob('*.jar'))}
    classes = {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in sorted(work.glob('*.class'))}
    subprocess.run([java_home + '/bin/java', *CLIENT_JVM_ARGS, '-cp', str(work) + os.pathsep + str(work / 'lib' / '*'),
                    class_name, '--self-test'], check=True, timeout=15)
    identity.write_text(json.dumps({'robot_image': image, 'java_home': java_home, 'source_sha256': source_hash,
                                    'class_name': class_name, 'client_jvm_args': CLIENT_JVM_ARGS,
                                    'dependencies': dependencies, 'classes': classes}, indent=2) + '\n')
    return work


def run(work, config):
    identity = json.loads((work / 'identity.json').read_text())
    if identity.get('client_jvm_args') != CLIENT_JVM_ARGS:
        raise RuntimeError('Native client memory/GC profile must pass preparation first')
    command = [identity['java_home'] + '/bin/java', *CLIENT_JVM_ARGS, '-cp',
               str(work) + os.pathsep + str(work / 'lib' / '*'), identity.get('class_name', 'MacDemoNativeTcpLoad')]
    # Preserve each real client outcome before a later role/finance check can
    # throw. Raw SDK output may contain sessions: private directory/files only,
    # and never persist the input credentials or print the raw output.
    evidence = Path(tempfile.mkdtemp(prefix='native-result-', dir=work))
    meta = {'started_at': datetime.now(timezone.utc).isoformat(),
            'request': {key: config[key] for key in ('prefix', 'seconds', 'location', 'user_id', 'symbol')
                        if key in config}, 'class_name': identity.get('class_name', 'MacDemoNativeTcpLoad'),
            'client_jvm_args': CLIENT_JVM_ARGS}

    def retain(stdout, stderr, returncode, timed_out=False):
        meta.update(returncode=returncode, timed_out=timed_out,
                    finished_at=datetime.now(timezone.utc).isoformat(), files={})
        for name, raw in [('stdout.txt', stdout), ('stderr.txt', stderr)]:
            data = raw if isinstance(raw, bytes) else (raw or '').encode('utf-8')
            with (evidence / name).open('xb') as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(data)
            meta['files'][name] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        proof = evidence / 'proof.json'
        with proof.open('x') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(meta, stream, indent=2)
            stream.write('\n')
        return proof

    try:
        completed = subprocess.run(command, input=json.dumps(config) + '\n', capture_output=True, text=True,
                                   timeout=config['seconds'] + 150)
    except subprocess.TimeoutExpired as timeout:
        proof = retain(timeout.stdout, timeout.stderr, None, timed_out=True)
        failure = RuntimeError('Native TCP client timed out; private evidence retained')
        failure.native_process_evidence = str(proof)
        raise failure from timeout
    proof = retain(completed.stdout, completed.stderr, completed.returncode)
    records = [line.removeprefix('T554_NATIVE_TCP_REPORT ') for line in completed.stdout.splitlines()
               if line.startswith('T554_NATIVE_TCP_REPORT ')]
    if completed.returncode or len(records) != 1:
        failures = [line for line in completed.stdout.splitlines() if line.startswith('T554_NATIVE_TCP_FAILURE ')]
        failure = RuntimeError('Native TCP client failed, exit=' + str(completed.returncode) + ' ' + ','.join(failures))
        failure.native_process_evidence = str(proof)
        raise failure
    result = json.loads(records[0])
    result['native_process_evidence'] = str(proof)
    return result
