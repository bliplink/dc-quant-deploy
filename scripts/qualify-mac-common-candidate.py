#!/usr/bin/env python3
"""Qualify one frozen Common JAR before the existing business build/deployment.

Runs only private Common fixtures. It never starts/stops business services,
edits business data, or grants ACK/READY. Do not overlap qualified pressure.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / 'tests/fixtures/common-release'
RESULT = re.compile(r'^COMMON_QUALIFICATION_RESULT discovered=(\d+) executed=(\d+) '
                    r'failures=(\d+) ignored=(\d+) skipped=(\d+) passed=(true|false)$', re.M)
COLD = (
    ('clean-local-owner', 'localOwnerColdRestartAfterPartialTakeoverKeepsAcknowledgedCommands'),
    ('interrupted-retained-owner', 'localOwnerColdRestartResumesInterruptedRetainedOwnerStage'),
    ('unpublished-local-tail', 'localOwnerColdRestartRetainsItsUnpublishedTailAndContinuesFromTheSignedHead'),
    ('mixed-cold-full-home', 'localOwnerColdRestartAfterPartialTakeoverKeepsAcknowledgedCommands'),
)
LIVE_LOCAL = (
    ('live-local-permanent-fence', 'poisonedLocalOwnerReplayCannotReopenAPermanentlyFencedEpoch'),
    ('live-local-repeated-heads', 'poisonedLocalOwnerReplaysRepeatedPublishedHeadsInTheSameEpoch'),
    ('live-local-published-head', 'poisonedLocalOwnerReplaysItsPublishedHeadWithoutRestartOrPeer'),
    ('live-local-private-tail', 'poisonedLocalOwnerExcludesItsUnpublishedTailWithoutRestartOrPeer'),
)

PARTITION_ISOLATION = (
    ('strict-partition-isolation', 'CommonCertifiedLivePoisonRecoveryTest',
     'signedRecoveringPartitionCannotBlockAnotherPhysicalTakeoverAndReturn'),
    ('retained-partition-isolation', 'CommonCertifiedFirstReadyE2AutomaticRecoveryTest',
     'heldRetainedOwnerDoesNotBlockAnotherTakeoverAfterPrimaryDies'),
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_result(path, safety=False):
    matches = RESULT.findall(path.read_text())
    if len(matches) != 1:
        raise ValueError('Exactly one complete qualification result is required: ' + str(path))
    discovered, executed, failures, ignored, skipped = map(int, matches[0][:5])
    if (matches[0][5] != 'true' or failures or ignored or discovered != executed + skipped
            or executed < (314 if safety else 1) or (safety and skipped > 3)
            or (not safety and skipped)):
        raise ValueError('Incomplete or unsuccessful qualification: ' + str(path))
    return dict(discovered=discovered, executed=executed, failures=failures,
                ignored=ignored, optional_external_historical_skips=skipped, log_sha256=sha(path))


def require_complete_qualification(candidate, results):
    """Read-only release check; physical Home alone cannot omit other gates."""
    candidate, results = candidate.resolve(strict=True), results.resolve(strict=True)
    work = candidate / 'qualification'
    state = json.loads((work / 'state.json').read_text())
    digest = (candidate / 'jar.sha').read_text().strip()
    revision = (candidate / 'commit.sha').read_text().strip()
    if (state.get('status') != 'PASS_COMMON_QUALIFICATION_BUSINESS_AND_PERFORMANCE_STILL_REQUIRED'
            or not state.get('finished_at') or state.get('business_mutations') is not False
            or state.get('production_go') is not False
            or not re.fullmatch('[a-f0-9]{64}', digest)
            or not re.fullmatch('[a-f0-9]{40}', revision)
            or state.get('common_sha256') != digest or state.get('common_revision') != revision
            or sha(candidate / 'common-tested-class-bytes.jar') != digest
            or Path(state.get('physical_result', '')).resolve() != results
            or (results / 'status').read_text().strip() != 'PASS'
            or sha(results / 'common.jar') != digest
            or state.get('physical_seal_sha256') != sha(results / 'verification.seal.json')):
        raise ValueError('Complete exact-JAR Common qualification is required before business build')
    required = {'compile-fixtures', 'compile-runner', 'safety', 'large-genesis-96m', 'historical-prefix'}
    required.update(name for name, _ in COLD + LIVE_LOCAL)
    required.update(name for name, _, _ in PARTITION_ISOLATION)
    stages = state.get('stages', [])
    names = [row.get('name') for row in stages]
    if len(names) != len(set(names)) or not required.issubset(names):
        raise ValueError('Common qualification stages are incomplete or duplicated')
    for row in stages:
        name = row['name']
        if not re.fullmatch('[a-z0-9-]+', name):
            raise ValueError('Invalid Common qualification stage')
        log = work / (name + '.log')
        if (row.get('exit_code') != 0 or not row.get('finished_at')
                or Path(row.get('log', '')).resolve() != log.resolve()
                or row.get('log_sha256') != sha(log)):
            raise ValueError('Common qualification log changed or did not finish: ' + name)
    if state.get('safety') != checked_result(work / 'safety.log', safety=True):
        raise ValueError('Common safety result differs from its complete original log')
    for name in ('large-genesis-96m', 'historical-prefix'):
        checked_result(work / (name + '.log'))
    for group, cases in (('cold', COLD), ('live_local', LIVE_LOCAL)):
        for name, _ in cases:
            if state.get(group, {}).get(name) != checked_result(work / (name + '.log')):
                raise ValueError('Common ' + name + ' result is incomplete')
    for name, _, _ in PARTITION_ISOLATION:
        if state.get('partition_isolation', {}).get(name) != isolation_result(work, name):
            raise ValueError('Incomplete physical partition isolation evidence: ' + name)
    return state


def isolation_result(work, name):
    proof = checked_result(work / (name + '.log'))
    if proof['executed'] != 1:
        raise ValueError('Expected one independently executed partition fault')
    if name == 'strict-partition-isolation':
        evidence = work / (name + '-evidence-live-poison') / 'held-signed-stage'
        marker = (evidence / 'held-stage-physical-proof.txt').read_text().splitlines()
        wals = [evidence / ('data-' + side.lower()) / 'DemoSvr' / ('DemoSvr' + side)
                / 'P001/epoch-4/business.wal' for side in ('A', 'B')]
        size = wals[0].stat().st_size
        digest = sha(wals[0])
        if (size <= 0 or wals[1].stat().st_size != size or sha(wals[1]) != digest
                or marker != ['held=P000 epoch=3 ready=false', 'home=P001 epoch=4 quorumAck=true',
                              'equalWalBytes=' + str(size), 'sha256=' + digest]):
            raise ValueError('Missing independent physical quorum commit while the other Stage is held')
        proof['equal_wal_sha256'] = digest
    else:
        evidence = work / (name + '-evidence')
        selected = (evidence / 'probe-later-takeover').read_text().strip()
        if not re.fullmatch(r'P[0-9]{3}', selected) or int(selected[1:]) >= 128:
            raise ValueError('Invalid original failed-owner partition in recovery proof')
        hashes = []
        for marker, partition in [('independent-local-risk-ack', selected), ('retained-162-local-risk-ack', 'P162')]:
            path = evidence / marker
            fields = path.read_text().splitlines()
            if (len(fields) != 5 or fields[:2] != ['partition=' + partition, 'epoch=3']
                    or not re.fullmatch('sequence=[1-9][0-9]*', fields[2])
                    or fields[3:] != ['quorumDurable=false', 'rpoRisk=true']):
                raise ValueError('Missing recovered physical LOCAL acknowledgement: ' + marker)
            hashes.append(sha(path))
        proof['local_receipts_sha256'] = hashes
    return proof


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('results', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    candidate = args.candidate.resolve(strict=True)
    results = args.results.resolve()
    if (not args.candidate.is_absolute() or not args.results.is_absolute()
            or results.exists() or results == candidate
            or candidate in results.parents or results in candidate.parents):
        parser.error('Use an existing absolute candidate and a separate new absolute results directory')
    expected = (candidate / 'jar.sha').read_text().strip()
    revision = (candidate / 'commit.sha').read_text().strip()
    jar = candidate / 'common-tested-class-bytes.jar'
    if (not re.fullmatch('[a-f0-9]{64}', expected) or sha(jar) != expected
            or not re.fullmatch('[a-f0-9]{40}', revision)):
        parser.error('Frozen candidate identity does not match its original JAR')
    work = candidate / 'qualification'
    if work.exists():
        parser.error('Candidate already has a qualification attempt; preserve it and freeze a new candidate')
    java = Path(subprocess.check_output(['/usr/libexec/java_home', '-v', '1.8'], text=True).strip())
    maven = os.environ.get('MAC_DEMO_MAVEN', str(REPO / '.work/t442-maven-tools/apache-maven-3.9.11/bin/mvn'))
    keys = Path(os.environ.get('MAC_DEMO_TEST_RSA_KEYS', str(Path.home() /
        'Documents/Codex/2026-10-18/referenced-chatgpt-conversation-this-is-an/work/common-ha-netty-v19-control-cache/v19-quorum-secrets')))
    for name in ('a/node.pk8', 'b/node.pk8', 'public/CommonHaDemoA.pub.der', 'public/CommonHaDemoB.pub.der'):
        if not (keys / name).is_file():
            parser.error('Original independent Demo test keys are required before qualification')
    processes = subprocess.check_output(['ps', '-axo', 'comm=,args='], text=True)
    if any('/bin/java' in line and any(name in line for name in
               ('MacDemoNativeTcpLoad', 'MacDemoNativeTcpOrderCancel')) for line in processes.splitlines()):
        parser.error('A native pressure window is active; preserve its measurement before Common qualification')
    lock = (candidate.parent / '.qualification.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    work.mkdir()
    (work / 'runner').mkdir()
    qualifier_source = work / 'qualifier-source.py'
    shutil.copy2(Path(__file__).resolve(), qualifier_source)
    state = {'status': 'RUNNING', 'started_at': datetime.now(timezone.utc).isoformat(),
             'common_revision': revision, 'common_sha256': expected, 'physical_result': str(results),
             'qualifier_source_sha256': sha(qualifier_source),
             'business_mutations': False, 'stages': [], 'production_go': False}
    # Existing verifier supports independent native and Home JVMs. Their
    # private directories and control sessions share only this frozen JAR.
    env = dict(os.environ, JAVA_HOME=str(java),
               MAC_DEMO_COMMON_PARALLEL_P0_JVMS=os.environ.get('MAC_DEMO_COMMON_PARALLEL_P0_JVMS', 'true'))
    full = full_output = None

    def save():
        pending = work / 'state.pending'
        pending.write_text(json.dumps(state, indent=2) + '\n')
        pending.replace(work / 'state.json')

    def phase(name, command, cwd=REPO):
        log = work / (name + '.log')
        row = {'name': name, 'started_at': datetime.now(timezone.utc).isoformat(), 'log': str(log)}
        state['stages'].append(row)
        state['current_stage'] = name
        save()
        print('START', name, flush=True)
        with log.open('x') as output:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = process.wait(timeout=2400)
            finally:
                stop(process)
        row.update(exit_code=code, finished_at=datetime.now(timezone.utc).isoformat(), log_sha256=sha(log))
        save()
        if code:
            raise RuntimeError(name + ' failed; original log retained')
        return log

    def terminate(signum, frame):
        raise KeyboardInterrupt('Qualification interrupted; retain every original result')

    signal.signal(signal.SIGTERM, terminate)
    save()
    try:
        dependencies = work / 'dependencies.classpath'
        phase('compile-fixtures', [maven, '-o', '-B', '-DskipTests', 'test-compile',
              'dependency:build-classpath', '-Dmdep.outputFile=' + str(dependencies)], cwd=candidate / 'source')
        runner = work / 'runner'
        shutil.copy2(FIXTURE / 'QualifiedCommonChecks.java', runner)
        shutil.copy2(FIXTURE / 'safety-tests.list', work)
        classpath = ':'.join((str(jar), str(candidate / 'source/target/test-classes'),
                              dependencies.read_text().strip(), str(runner)))
        phase('compile-runner', [str(java / 'bin/javac'), '-cp', classpath, '-d', str(runner),
                                str(runner / 'QualifiedCommonChecks.java')])
        command = [str(java / 'bin/java'), '-Xms32m', '-Xmx512m',
                   '-Dotc.demo.existing.keys=' + str(keys), '-cp', classpath, 'QualifiedCommonChecks']
        # Exercise the newly repaired availability boundary first so a
        # regression stops before the longer unchanged physical suite.
        # Every existing safety, cold and native gate remains mandatory.
        state['live_local'] = {}
        for name, method in LIVE_LOCAL:
            live_command = command[:]
            live_command.insert(1, '-Dt554.fixture.evidence.directory=' + str(work / (name + '-evidence')))
            log = phase(name, live_command + ['--method',
                        'com.app.common.replication.CommonCertifiedFirstReadyE2AutomaticRecoveryTest', method])
            state['live_local'][name] = checked_result(log)
            marker = ('T554_LIVE_LOCAL_POISON_PERMANENT_FENCE_REJECTED_HEALTHY_SHARD_CONTINUES'
                      if name == 'live-local-permanent-fence' else
                      'T554_LIVE_LOCAL_POISON_AUTHENTICATED_REPLAY_SAME_RUNTIME_NO_PEER_AND_EXPORT_PASS')
            if marker not in log.read_text():
                raise ValueError('Missing live LOCAL recovery evidence: ' + name)
            save()
        state['partition_isolation'] = {}
        for name, test_class, method in PARTITION_ISOLATION:
            isolated = command[:]
            isolated.insert(1, '-Dt554.fixture.evidence.directory=' + str(work / (name + '-evidence')))
            phase(name, isolated + ['--method', 'com.app.common.replication.' + test_class, method])
            state['partition_isolation'][name] = isolation_result(work, name)
            save()
        classes = (work / 'safety-tests.list').read_text().splitlines()
        state['safety'] = checked_result(phase('safety', command + ['--safety', *classes]), safety=True)
        save()
        large = [str(java / 'bin/java'), '-Xms32m', '-Xmx96m', '-cp', classpath, 'QualifiedCommonChecks']
        log = phase('large-genesis-96m', large + ['--method',
                    'com.app.common.replication.CommonCertifiedOpaqueGenesisAnyEpochTest',
                    'largeSignedGenesisHistoryStreamsWithoutRetainingAllCommands'])
        checked_result(log)
        for marker in ('T554_72_MIB_ORIGINAL_TWO_RSA_GENESIS_STREAMING_REPLAY_NO_READY_PASS',
                       'T554_LARGE_CERTIFIED_HISTORY_WITNESS_DISK_BUDGET_NOT_HEAP_BUDGET_PASS'):
            if marker not in log.read_text():
                raise ValueError('Missing bounded-memory historical proof: ' + marker)
        checked_result(phase('historical-prefix', command + ['--classes',
            'com.app.common.replication.CommonHistoricalCertifiedPrefixWithTailTest',
            'com.app.common.replication.CommonCertifiedOpaqueHistoricalReplayTest',
            'com.app.common.replication.CommonCertifiedE2LargeColdHistoryTest']))
        # Private fixture directories and independent ZK sessions; the same
        # immutable JAR remains first in every parent and child classpath.
        full_output = (work / 'full-physical.log').open('x')
        state['physical_fixture_revision'] = env.get('MAC_DEMO_COMMON_P0_FIXTURE_REVISION', revision)
        full = subprocess.Popen(['bash', str(REPO / 'scripts/verify-mac-common-failover.sh'),
                                 str(candidate), expected, str(results)], cwd=REPO,
            env=dict(env, MAC_DEMO_REQUIRE_INTERRUPTED_RETURN='true',
                     MAC_DEMO_COMMON_P0_FIXTURE_REVISION=env.get('MAC_DEMO_COMMON_P0_FIXTURE_REVISION', revision)),
            stdout=full_output, stderr=subprocess.STDOUT, start_new_session=True)
        state['physical_pid'] = full.pid
        state['cold'] = {}
        for name, method in COLD:
            cold_command = command[:]
            if name == 'mixed-cold-full-home':
                cold_command.insert(1, '-Dt554.verify.cold.owner.complete.return=true')
            log = phase(name, cold_command + ['--method',
                        'com.app.common.replication.CommonCertifiedFirstReadyE2AutomaticRecoveryTest', method])
            state['cold'][name] = checked_result(log)
            if name == 'unpublished-local-tail' and 'T554_PRIVATE_LOCAL_UNPUBLISHED_TAIL_COLD_REPLAY_AND_NEXT_ACK_PASS' not in log.read_text():
                raise ValueError('Missing private-tail cold replay evidence')
            if name == 'mixed-cold-full-home' and 'T554_COLD_LOCAL_OWNER_AUTOMATIC_MIXED_256_HOME_WAL_AND_REARMED_SNAPSHOT_MATCH_PASS' not in log.read_text():
                raise ValueError('Missing mixed full Home evidence')
            save()
        state['current_stage'] = 'full-physical'
        save()
        if full.wait(timeout=5400):
            raise RuntimeError('Independent physical failover failed; preserve its original evidence')
        seal = json.loads((results / 'verification.seal.json').read_text())
        if ((results / 'status').read_text().strip() != 'PASS' or sha(results / 'common.jar') != expected
                or not seal['normal_dual_async_full_queue_primary_crash']
                or not seal['normal_dual_async_current_local_history'] or not seal['interrupted_local_rearm']):
            raise ValueError('Exact full physical verification did not finish all mandatory gates')
        state.update(status='PASS_COMMON_QUALIFICATION_BUSINESS_AND_PERFORMANCE_STILL_REQUIRED',
                     physical_seal_sha256=sha(results / 'verification.seal.json'))
    except BaseException as error:
        state.update(status='NO_GO', failure=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        if full is not None:
            stop(full)
        if full_output is not None:
            full_output.close()
        state['finished_at'] = datetime.now(timezone.utc).isoformat()
        save()
    print(state['status'], work / 'state.json', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
