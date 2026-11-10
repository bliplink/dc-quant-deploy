"""Drain a bound local research wrapper without stopping any of its calculation children."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil

from recovery.run_fit_risk_catalog_batch import read, write_status
from recovery.watch_fixed_primary_supplements import parent_alive


def identity(process):
    return {'pid': process.pid, 'create_time': process.create_time(), 'command': process.cmdline()}


def require_local_research_parent(pid, folder):
    process = psutil.Process(pid)
    bound = identity(process)
    command = bound['command']
    if ('-m' not in command or '--output-dir' not in command
            or command[command.index('-m') + 1] != 'recovery.run_fit_risk_catalog_batch'
            or Path(command[command.index('--output-dir') + 1]).resolve() != folder.resolve()
            or not process.is_running() or process.status() == psutil.STATUS_STOPPED):
        raise ValueError('exact live unsuspended remaining-catalog wrapper required')
    return bound


def calculation_children(process):
    """The wrapper has a persistent Windows console host, which is not a calculation."""
    children = []
    for child in process.children(recursive=True):
        try:
            if child.name().lower() == 'conhost.exe':
                continue
            if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                children.append(identity(child))
        except psutil.NoSuchProcess:
            pass
    return children


def guardian(intent_path):
    intent = read(intent_path)
    target, owner = intent['parent'], intent['owner']
    write_status(intent_path.with_name('GUARDIAN_READY.json'),
                 {'parent': target, 'owner': owner, 'guardian': identity(psutil.Process())})
    while True:
        current = read(intent_path)
        if current['phase'] in ('TRANSFERRED', 'ABORTED') or not parent_alive(target):
            return
        if not parent_alive(owner):
            # If the controller crashes between suspend and its next ledger write,
            # ARMED must also restore the exact old wrapper, never its children.
            psutil.Process(target['pid']).resume()
            write_status(intent_path.with_name('GUARDIAN_RESTORED.json'),
                         {'parent': target, 'reason': 'bound handoff owner exited', 'children_stopped': False})
            return
        time.sleep(.25)


def drain_and_stop(bound, output, verify_checkpoint, timeout=900):
    """Terminate ONLY the suspended orchestration parent after all children completed.

    On any pre-transfer exception resume it. A separate guardian handles abrupt
    owner termination; no signals are sent to a financial or compilation child.
    """
    if not parent_alive(bound):
        raise ValueError('research parent identity changed before handoff')
    output = Path(output)
    intent_path = output / 'HANDOFF_INTENT.json'
    if intent_path.exists():
        raise ValueError('preserve prior handoff attempt for explicit diagnosis')
    intent = {'parent': bound, 'owner': identity(psutil.Process()), 'phase': 'ARMED',
              'children_stopped': False, 'production_write': False}
    write_status(intent_path, intent)
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    with (output / 'guardian.log').open('x', encoding='utf-8') as log:
        watcher = subprocess.Popen([sys.executable, '-u', '-m', 'recovery.research_control_handoff',
            '--guardian', str(intent_path)], stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
    process, paused = psutil.Process(bound['pid']), False
    try:
        deadline = time.monotonic() + 15
        while not intent_path.with_name('GUARDIAN_READY.json').exists():
            if watcher.poll() is not None or time.monotonic() > deadline:
                raise ValueError('handoff guardian did not become ready')
            time.sleep(.05)
        ready = read(intent_path.with_name('GUARDIAN_READY.json'))
        if (ready.get('parent') != bound or ready.get('owner') != intent['owner']
                or ready.get('guardian', {}).get('pid') != watcher.pid or not parent_alive(ready['guardian'])):
            raise ValueError('guardian identity mismatch')
        if not parent_alive(bound):
            raise ValueError('parent exited before suspension')
        process.suspend()
        paused = True
        intent['phase'] = 'DRAINING'
        write_status(intent_path, intent)
        deadline = time.monotonic() + timeout
        while True:
            if not parent_alive(bound):
                raise ValueError('parent disappeared before checkpoint verification')
            children = calculation_children(process)
            write_status(output / 'handoff-status.json', {'phase': 'DRAINING', 'children': children,
                'parent': bound, 'children_stopped': False, 'production_write': False})
            if not children:
                break
            if time.monotonic() > deadline:
                raise ValueError('child drain timed out; resume old wrapper, never terminate its calculations')
            time.sleep(.5)
        checkpoint = verify_checkpoint()
        write_status(output / 'HANDOFF_CHECKPOINT.json', checkpoint)
        if calculation_children(process) or not parent_alive(bound) or watcher.poll() is not None:
            raise ValueError('handoff ownership/child state changed before parent transfer')
        intent['phase'] = 'TERMINATING_PARENT'
        write_status(intent_path, intent)
        process.terminate()
        process.wait(timeout=10)
        paused = False
        intent.update(phase='TRANSFERRED', checkpoint_verified=True)
        write_status(intent_path, intent)
        return checkpoint
    finally:
        if paused and parent_alive(bound):
            process.resume()
        if parent_alive(bound):
            intent['phase'] = 'ABORTED'
            write_status(intent_path, intent)
        watcher.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guardian', type=Path, required=True)
    guardian(parser.parse_args().guardian)


if __name__ == '__main__':
    main()
