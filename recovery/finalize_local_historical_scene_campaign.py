"""Wait for a local scene campaign, then assemble only a fully verified input.

This Windows helper performs no production IO. The assembler still validates
all checkpoints, hashes, quality flags, and canonical scene timestamps.
"""

import argparse
import ctypes
import json
import os
from datetime import date
from pathlib import Path

from recovery.assemble_local_historical_scene_input import assemble


SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x00000102


def wait_for_process(pid):
    if os.name != 'nt':
        raise RuntimeError('this completion watcher is for the local Windows host')
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        raise RuntimeError('campaign process not found: %d' % pid)
    try:
        while True:
            result = kernel.WaitForSingleObject(ctypes.c_void_p(handle), 60000)
            if result == WAIT_OBJECT_0:
                return
            if result != WAIT_TIMEOUT:
                raise RuntimeError('could not wait for campaign process: %d' % result)
    finally:
        kernel.CloseHandle(ctypes.c_void_p(handle))


def require_completed(status_path):
    status = json.loads(status_path.read_text(encoding='utf-8'))
    if (status.get('completed_chunks') != 260 or status.get('total_chunks') != 260
            or 'failed_chunk' in status or 'waiting_chunk' in status):
        raise RuntimeError('campaign is not complete; see %s' % status_path)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait-pid', type=int, required=True)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--campaign-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.wait_pid <= 0:
        parser.error('--wait-pid must be positive')
    print('waiting for campaign pid', args.wait_pid, flush=True)
    wait_for_process(args.wait_pid)
    require_completed(args.campaign_dir / 'status.json')
    metadata = assemble(args.input_dir.resolve(), args.campaign_dir.resolve(),
                        args.output_dir.resolve(), date(2025, 10, 12))
    print('READY', args.output_dir, 'symbols', len(metadata['symbols']), flush=True)


if __name__ == '__main__':
    main()
