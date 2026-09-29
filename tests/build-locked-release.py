#!/usr/bin/env python3
"""Build committed service archives; never checkout/fetch or rewrite a user's repo.

An immutable generic Common release is an input, not the root SNAPSHOT project.
The pinned DC Common library is built once before any service consumes it.
Failures are resumable with --only; nothing is automatically deployed or deleted.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def run(argv, log=None, **kwargs):
    if log:
        with Path(log).open('a') as output:
            result = subprocess.run(argv, stdout=output, stderr=subprocess.STDOUT, **kwargs)
        if result.returncode:
            raise RuntimeError(f'command failed ({result.returncode}); see {log}')
        return ''
    return subprocess.check_output(argv, text=True, **kwargs).strip()


def prepare(component, root):
    name, revision = component['name'], component['revision']
    if not re.fullmatch(r'[a-z][a-z0-9-]*', name) or not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('invalid locked name/revision')
    repo = component['repository']
    if run(['git', '-C', repo, 'rev-parse', revision + '^{commit}']) != revision:
        raise ValueError(f'{name}: revision is not an exact commit')
    destination = root / name
    marker = destination / '.locked-source-revision'
    if destination.exists():
        if not marker.is_file() or marker.read_text().strip() != revision:
            raise ValueError(f'refusing to replace existing build directory: {destination}')
        return destination
    destination.mkdir()
    # Git archive excludes dirty files, ignored build outputs and .git metadata.
    archive = subprocess.Popen(['git', '-C', repo, 'archive', revision], stdout=subprocess.PIPE)
    extracted = subprocess.run(['tar', '-xf', '-', '-C', str(destination)], stdin=archive.stdout)
    archive.stdout.close()
    if extracted.returncode or archive.wait():
        raise RuntimeError(f'{name}: committed archive failed')
    marker.write_text(revision + '\n')
    return destination


def test_summary(source):
    totals = dict(suites=0, tests=0, failures=0, errors=0, skipped=0)
    for path in (source / 'target/surefire-reports').glob('TEST-*.xml'):
        report = ET.parse(path).getroot()
        totals['suites'] += 1
        for key in ('tests', 'failures', 'errors', 'skipped'):
            totals[key] += int(report.get(key, 0))
    if totals['failures'] or totals['errors']:
        raise RuntimeError(f'failed tests: {source.name}: {totals}')
    return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', required=True, type=Path)
    parser.add_argument('--build-root', required=True, type=Path)
    parser.add_argument('--m2', required=True, type=Path)
    parser.add_argument('--settings', required=True, type=Path)
    parser.add_argument('--jobs', type=int, choices=[1, 2], default=2)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--only', nargs='+')
    parser.add_argument('--collect-only', action='store_true', help='collect already-successful exact builds without rebuilding')
    parser.add_argument('--cached-web-bases', action='store_true', help='use verified cached Node/nginx runtimes when registry is unavailable')
    parser.add_argument('--trade-node-build-base', default='node:16-bullseye', help='optional exact local Node16/npm cache image')
    parser.add_argument('--prerequisite-lock', type=Path)
    parser.add_argument('--prerequisite-root', type=Path)
    args = parser.parse_args()
    if args.prerequisite_lock:
        if not args.prerequisite_root:
            raise ValueError('--prerequisite-root required')
        args.prerequisite_root.mkdir(exist_ok=True)
        import sys
        command = [sys.executable, __file__, '--lock', str(args.prerequisite_lock),
            '--build-root', str(args.prerequisite_root), '--m2', str(args.m2), '--settings', str(args.settings)]
        if args.offline:
            command.append('--offline')
        run(command)
    lock = json.loads(args.lock.read_text())
    root = args.build_root.resolve()
    if not root.is_dir() or any(root.iterdir()) and not (root / 'release-lock.json').exists():
        raise ValueError('build root must be an empty dedicated directory or a matching previous build')
    copied_lock = root / 'release-lock.json'
    if copied_lock.exists() and json.loads(copied_lock.read_text()) != lock:
        raise ValueError('cannot reuse build root with a different source lock')
    copied_lock.write_text(json.dumps(lock, indent=2) + '\n')
    cache = args.m2.resolve()
    baseline = cache / 'repository/io/github/bliplink/com.app.common/3.0.14/com.app.common-3.0.14.jar'
    if digest(baseline) != lock['genericCommon']['sha256']:
        raise ValueError('immutable Common 3.0.14 input mismatch')
    components = lock['components']
    if args.only:
        if set(args.only) - {item['name'] for item in components}:
            raise ValueError('unknown --only component')
        components = [item for item in components if item['name'] in args.only]
    images = {}
    evidence_path = root / 'build-evidence.json'
    if evidence_path.exists():
        images = json.loads(evidence_path.read_text())['components']
    maven_image = run(['docker', 'image', 'inspect', 'maven:3.9.11-eclipse-temurin-8', '--format', '{{.Id}}'])
    jre_image = run(['docker', 'image', 'inspect', 'eclipse-temurin:8-jre', '--format', '{{.Id}}'])

    def build(component):
        name = component['name']
        source = prepare(component, root)
        log = root / (name + '.build.log')
        started = time.time()
        print(f'[locked-build] START {name} {component["revision"][:12]}', flush=True)
        result = dict(revision=component['revision'], source=str(source), buildLog=str(log))
        if component['type'] in ('java', 'library'):
            argv = ['docker', 'run', '--rm', '--memory=2g', '--cpus=2',
                    '-e', 'MAVEN_OPTS=-Xmx512m',
                    '-v', f'{cache}:/root/.m2', '-v', f'{source}:/workspace',
                    '-v', f'{args.settings.resolve()}:/empty-settings.xml:ro', '-w', '/workspace']
            if args.offline:
                argv += ['--network', 'none']
            argv += [maven_image, 'mvn', '-B', '-nsu', '-s', '/empty-settings.xml',
                     '-gs', '/empty-settings.xml', '-DargLine=-Xmx1024m']
            if args.offline:
                argv += ['-o']
            argv += ['test', 'install' if component['type'] == 'library' else 'package',
                     'org.apache.maven.plugins:maven-dependency-plugin:3.7.0:copy-dependencies',
                     '-DincludeScope=runtime', '-DoutputDirectory=target/dependency']
            if not args.collect_only:
                run(argv, log=log)
            result['tests'] = test_summary(source)
            result['dependencies'] = {path.name: digest(path) for path in sorted((source / 'target/dependency').glob('*.jar'))}
            if component['type'] == 'java':
                if result['dependencies'].get(baseline.name) != lock['genericCommon']['sha256']:
                    raise ValueError(f'{name}: did not embed the exact Common 3.0.14 baseline')
                expected_dc = digest(cache / 'repository/com/app/dc/com.app.dc/0.0.4-SNAPSHOT/com.app.dc-0.0.4-SNAPSHOT.jar')
                if name != 'gateway' and result['dependencies'].get('com.app.dc-0.0.4-SNAPSHOT.jar') != expected_dc:
                    raise ValueError(f'{name}: DC Common differs from the pinned build')
        if component['type'] != 'library':
            image = component['image']
            dockerfile = source / 'Dockerfile'
            # Web package-lock files are inputs. Do not regenerate a mutable npm install graph.
            if component['type'] == 'web':
                content = dockerfile.read_text().replace('RUN npm install\n', 'RUN npm ci --no-audit --no-fund\n')
                dockerfile = source / 'Dockerfile.locked-release'
                dockerfile.write_text(content)
                result['packageLockSha256'] = digest(source / 'package-lock.json')
            build_args = []
            if component['type'] == 'web' and args.cached_web_bases:
                cache_refs = {
                    'trade-web': (args.trade_node_build_base, 'ghcr.io/bliplink/dc-saas-trade-web:sha-1ca247a87f039abea119fa7283798aa176f1d074', 'Trade.Dockerfile', 18088),
                    'tenant-web': ('mcr.microsoft.com/playwright:v1.55.0-noble', 'ghcr.io/bliplink/dc-saas-tenant-web:sha-30a81a822e10', 'Console.Dockerfile', 18092),
                    'platform-web': ('mcr.microsoft.com/playwright:v1.55.0-noble', 'ghcr.io/bliplink/dc-saas-platform-web:sha-5a7a5318ea0b', 'Console.Dockerfile', 18090)}
                node_ref, runtime_ref, fixture_name, port = cache_refs[name]
                node_id = run(['docker', 'image', 'inspect', node_ref, '--format', '{{.Id}}'])
                runtime_id = run(['docker', 'image', 'inspect', runtime_ref, '--format', '{{.Id}}'])
                dockerfile = Path(__file__).resolve().parent / 'fixtures/locked-web' / fixture_name
                result['cachedWebBases'] = dict(node=node_id, nginxRuntime=runtime_id, dockerfileSha256=digest(dockerfile))
                build_args = ['--build-arg', 'NODE_BUILD_BASE=' + node_id,
                    '--build-arg', 'WEB_RUNTIME_BASE=' + runtime_id, '--build-arg', 'WEB_PORT=' + str(port)]
            labels = ['org.opencontainers.image.revision=' + component['revision'],
                      'dc.release.lock.sha256=' + digest(args.lock),
                      'dc.common.revision=released-common-3.0.14',
                      'dc.common.gav=' + lock['genericCommon']['gav'],
                      'dc.common.jar.sha256=' + lock['genericCommon']['sha256']]
            argv = ['docker', 'build', '--pull=false', '-f', str(dockerfile), '-t', image] + build_args
            for label in labels:
                argv += ['--label', label]
            argv += ['--build-arg', 'SERVICE_REVISION=' + component['revision'],
                     '--build-arg', 'COMMON_REVISION=released-common-3.0.14',
                     '--build-arg', 'COMMON_GAV=' + lock['genericCommon']['gav'],
                     '--build-arg', 'COMMON_JAR_SHA256=' + lock['genericCommon']['sha256'], str(source)]
            if args.collect_only:
                if ('Successfully tagged ' + image) not in log.read_text():
                    raise ValueError(f'{name}: no successful exact image build to collect')
            else:
                run(argv, log=log)
            result['image'] = image
            result['imageId'] = run(['docker', 'image', 'inspect', image, '--format', '{{.Id}}'])
            actual_revision = run(['docker', 'image', 'inspect', image, '--format', '{{index .Config.Labels "org.opencontainers.image.revision"}}'])
            if actual_revision != component['revision']:
                raise ValueError(f'{name}: built image revision mismatch')
        if digest(baseline) != lock['genericCommon']['sha256']:
            raise ValueError('immutable Common input was replaced during build')
        result['elapsedSeconds'] = round(time.time() - started, 3)
        print(f'[locked-build] PASS {name} {result.get("tests", {})}', flush=True)
        return name, result

    def record(result):
        name, value = result
        import fcntl
        with (root / '.evidence.lock').open('a') as evidence_lock:
            fcntl.flock(evidence_lock, fcntl.LOCK_EX)
            payload = json.loads(evidence_path.read_text()) if evidence_path.exists() else {}
            payload.update(releaseId=lock['releaseId'], mavenImage=maven_image, jreImage=jre_image)
            payload.setdefault('components', {}).update(images)
            payload['components'][name] = value
            if args.prerequisite_root:
                payload['prerequisites'] = json.loads((args.prerequisite_root / 'build-evidence.json').read_text())
            evidence_path.write_text(json.dumps(payload, indent=2) + '\n')
            images[name] = value

    for component in components:
        if component['type'] == 'library':
            record(build(component))
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(build, item) for item in components if item['type'] != 'library']
        failures = []
        for future in concurrent.futures.as_completed(futures):
            try:
                record(future.result())
            except Exception as error:
                failures.append(str(error))
                print('[locked-build] FAIL ' + str(error), flush=True)
    if failures:
        raise RuntimeError('; '.join(failures))
    print(f'[locked-build] evidence={evidence_path}', flush=True)


if __name__ == '__main__':
    main()
