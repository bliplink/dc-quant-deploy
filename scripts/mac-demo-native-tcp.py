"""Prepare and run the deployed GateWayApi as a bounded native TCP test client."""
import hashlib
import json
import os
from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'tests/MacDemoNativeTcpLoad.java'


def prepare(root, source=SOURCE, class_name='MacDemoNativeTcpLoad'):
    if source.stem != class_name or not class_name.isidentifier():
        raise ValueError('Native client source and Java class must match')
    image = subprocess.check_output(['docker', 'inspect', '-f', '{{.Image}}', 'dc-saas-robotsvr'], text=True).strip()
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    work = root / ('native-tcp-client-' + source_hash[:12] + '-' + image.split(':')[-1][:12])
    identity = work / 'identity.json'
    if identity.exists():
        recorded = json.loads(identity.read_text())
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
    subprocess.run([java_home + '/bin/java', '-cp', str(work) + os.pathsep + str(work / 'lib' / '*'),
                    class_name, '--self-test'], check=True, timeout=15)
    identity.write_text(json.dumps({'robot_image': image, 'java_home': java_home, 'source_sha256': source_hash,
                                    'class_name': class_name, 'dependencies': dependencies, 'classes': classes}, indent=2) + '\n')
    return work


def run(work, config):
    identity = json.loads((work / 'identity.json').read_text())
    command = [identity['java_home'] + '/bin/java', '-Xms32m', '-Xmx256m', '-cp',
               str(work) + os.pathsep + str(work / 'lib' / '*'), identity.get('class_name', 'MacDemoNativeTcpLoad')]
    completed = subprocess.run(command, input=json.dumps(config) + '\n', capture_output=True, text=True,
                               timeout=config['seconds'] + 150)
    records = [line.removeprefix('T554_NATIVE_TCP_REPORT ') for line in completed.stdout.splitlines()
               if line.startswith('T554_NATIVE_TCP_REPORT ')]
    if completed.returncode or len(records) != 1:
        failures = [line for line in completed.stdout.splitlines() if line.startswith('T554_NATIVE_TCP_FAILURE ')]
        raise RuntimeError('Native TCP client failed, exit=' + str(completed.returncode) + ' ' + ','.join(failures))
    return json.loads(records[0])
