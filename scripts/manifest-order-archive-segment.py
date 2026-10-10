#!/usr/bin/env python3
"""Generate a read-only SHA-256 manifest for ONE sealed OrderSvr CQ archive.

This is a local integrity inventory, NOT committed-watermark attestation,
backup proof, a recovery certificate or GC authorization.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

NAME = re.compile(r'^(P\d{3})-epoch(\d+)-seq(\d+)-(\d+)$')


def generate(archive_path):
    original = Path(archive_path)
    if original.is_symlink() or not original.is_dir():
        raise ValueError('archive must be an existing nonsymlink directory')
    if original.parent.name != '.archive' or original.parent.is_symlink():
        raise ValueError('archive must live directly under a nonsymlink .archive directory')
    match = NAME.fullmatch(original.name)
    if not match:
        raise ValueError('unrecognized CQ archive name')
    records = []
    for base, folders, filenames in os.walk(original, followlinks=False):
        folders.sort()
        for folder in folders:
            p = Path(base) / folder
            if p.is_symlink():
                raise ValueError('symlink directory inside archive')
        for name in sorted(filenames):
            p = Path(base) / name
            if p.is_symlink() or not p.is_file():
                raise ValueError('unsafe non-regular archive file')
            before = p.stat()
            digest = hashlib.sha256()
            with p.open('rb') as handle:
                while True:
                    piece = handle.read(1024 * 1024)
                    if not piece:
                        break
                    digest.update(piece)
            after = p.stat()
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                    after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                raise ValueError('archive changed while hashing; refusing partial manifest')
            records.append({'path':str(p.relative_to(original)), 'sha256':digest.hexdigest(),
                            'sizeBytes':before.st_size})
    if not records:
        raise ValueError('empty archive cannot be certified')
    records.sort(key=lambda row:row['path'])
    return {'schema':'otc-order-archive-hash-manifest-v1',
            'archiveName':original.name, 'partition':match.group(1),
            'epochNameHint':int(match.group(2)),
            'lastSequenceNameHint':int(match.group(3)),
            'checkedAtUtc':datetime.now(timezone.utc).isoformat(),
            'files':records,
            'totalLogicalBytes':sum(x['sizeBytes'] for x in records),
            'sourceReadOnly':True, 'externalBackupVerified':False,
            'snapshotRestorationVerified':False,
            'replicaAndProjectionWatermarksAttested':False,
            'deletionAuthorized':False, 'retentionDecision':'HOLD'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args(argv)
    root=Path(args.archive).resolve()
    out=Path(args.output).resolve()
    # Writing into the runtime journal tree could interfere with Chronicle
    # or create a misleading artifact eligible for future GC.
    journal=root.parent.parent
    if out == journal or journal in out.parents:
        raise ValueError('manifest output must be outside the journal tree')
    if out.is_symlink():
        raise ValueError('manifest output may not be a symlink')
    if out.exists():
        raise ValueError('manifest output already exists; use a versioned filename')
    data=generate(args.archive)
    out.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive create: never clobber an existing proof/manifest.
    with out.open('x',encoding='utf8') as handle:
        json.dump(data,handle,indent=2,ensure_ascii=False)
        handle.write('\n')
    print(json.dumps({'archiveName':data['archiveName'],'files':len(data['files']),
                      'logicalBytes':data['totalLogicalBytes'],'deletionAuthorized':False,
                      'output':str(out)}))
    return 0

if __name__=='__main__':
    try:
        sys.exit(main())
    except (OSError,ValueError) as exc:
        print('ORDER_ARCHIVE_MANIFEST_DENIED '+str(exc),file=sys.stderr)
        sys.exit(2)
