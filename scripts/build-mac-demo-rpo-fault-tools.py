#!/usr/bin/env python3
"""Build bounded Demo fault tools and run their Mac/Linux self-tests."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--linux-image', required=True,
                        help='Existing Java 8 business image ID; never pulled or started as a service')
    args = parser.parse_args()
    os.umask(0o077)
    root = args.output.expanduser().absolute()
    root.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[1] / 'tests/fixtures/async-rpo'
    java = Path(subprocess.check_output(['/usr/libexec/java_home', '-v', '1.8'], text=True).strip())
    image = json.loads(subprocess.check_output(
        ['docker', 'image', 'inspect', args.linux_image], text=True))[0]['Id']
    groups = (
        ('T554OrderDeliveryPauseAgent', 'fault-agent.jar', 'self-test', 'linux-self-test',
         'T554_DELIVERY_FAULT_EXPLICIT_RESUME_DEADLINE_AND_FAILED_SETUP_SELFTEST_PASS'),
        ('T554PhysicalCommitHeadObserverAgent', 'head-observer.jar',
         'head-observer-self-test', 'head-observer-linux-self-test',
         'T554_PHYSICAL_HEAD_READ_OBSERVER_SELF_TEST_PASS'),
        ('T554CommonReplicationPauseAgent', 'replication-pause-agent.jar',
         'replication-self-test', 'replication-linux-self-test',
         'T554_REPLICATION_FAULT_REQUESTED_DEADLINE_AND_REJECTED_SETUP_SELFTEST_PASS'))
    files = [source / 'T554RpoAttach.java']
    for agent, _, _, _, _ in groups:
        files.extend((source / (agent + '.java'), source / (agent + 'Test.java')))
    evidence = {'status': 'NO_GO', 'linux_image_id': image,
                'sources': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                'scope': 'Standalone bounded fault self-tests only; no business volume, network, ACK or role changes'}
    (root / 'build.json').write_text(json.dumps(evidence, indent=2) + '\n')

    def run(name, command):
        with (root / (name + '.log')).open('x') as log:
            subprocess.run([str(x) for x in command], check=True,
                           stdout=log, stderr=subprocess.STDOUT, timeout=90)

    run('compile', [java / 'bin/javac', '-source', '8', '-target', '8', '-cp',
                    java / 'lib/tools.jar', '-d', root, *files])
    for agent, jar, mac, linux, marker in groups:
        manifest = root / (agent + '.mf')
        manifest.write_text('Manifest-Version: 1.0\nAgent-Class: ' + agent +
                            '\nCan-Redefine-Classes: false\nCan-Retransform-Classes: false\n\n')
        run(agent + '-jar', [java / 'bin/jar', 'cfm', root / jar, manifest,
                             '-C', root, agent + '.class'])
        run(mac, [java / 'bin/java', '-Xmx96m', '-cp', root, agent + 'Test'])
        run(linux, ['docker', 'run', '--rm', '--pull=never', '--network=none',
                     '--read-only', '--cpus=1', '--memory=256m', '--pids-limit=128',
                     '--tmpfs', '/tmp:rw,size=32m', '--mount',
                     'type=bind,src=' + str(root) + ',dst=/tools,readonly',
                     '--entrypoint', '/opt/java/openjdk/bin/java', image,
                     '-Xmx96m', '-cp', '/tools', agent + 'Test'])
        for name in (mac, linux):
            if marker not in (root / (name + '.log')).read_text():
                raise RuntimeError('Missing independent self-test marker: ' + name)
            (root / (name + '.status')).write_text('PASS\n')
    evidence.update(status='MAC_AND_LINUX_ALL_BOUNDED_FAULT_TOOLS_SELFTEST_PASS',
                    jars={jar: hashlib.sha256((root / jar).read_bytes()).hexdigest()
                          for _, jar, _, _, _ in groups})
    (root / 'build.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(evidence['status'], root)


if __name__ == '__main__':
    main()
