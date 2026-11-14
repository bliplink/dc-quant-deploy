#!/usr/bin/env python3
"""Retain the qualified Gateway code while aligning its exact Common/shared dependencies."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def read(*args):
    return subprocess.check_output([str(x) for x in args],text=True).strip()


def main():
    if len(sys.argv)!=4:
        raise SystemExit('usage: build-mac-demo-gateway-dependencies.py QUALIFIED_GATEWAY_IMAGE CORE_BUILD NEW_OUTPUT')
    image,build,out=sys.argv[1],Path(sys.argv[2]).resolve(strict=True),Path(sys.argv[3]).absolute()
    os.umask(0o077)
    assert out.is_absolute() and not out.exists()
    values=dict(line.split('=',1) for line in (build/'images.env').read_text().splitlines() if line)
    base=json.loads(read('docker','image','inspect',image))[0]
    revision=(base['Config'].get('Labels') or {}).get('dc.gateway.guard.revision','')
    assert len(revision)==40 and all(x in '0123456789abcdef' for x in revision)
    out.mkdir(mode=0o700);(out/'lib').mkdir()
    for source,target,key in [('common.jar','com.app.common-mac-demo.jar','common_sha256'),
                              ('shared.jar','com.app.dc-mac-demo.jar','shared_sha256')]:
        assert hashlib.sha256((build/source).read_bytes()).hexdigest()==values[key]
        shutil.copy2(build/source,out/'lib'/target)
    candidate='local/otc-mac-demo-gateway:'+values['common_sha256'][:12]+'-'+values['shared_sha256'][:12]+'-'+revision[:8]
    (out/'Dockerfile').write_text('FROM '+base['Id']+'\n'
        +'RUN rm -f /srv/dc/dc/GW/lib/com.app.common-*.jar /srv/dc/dc/GW/lib/com.app.dc-*.jar\n'
        +'COPY lib/ /srv/dc/dc/GW/lib/\nLABEL dc.common.jar.sha256='+values['common_sha256']
        +' dc.common.revision='+values['common_revision']+' dc.shared.jar.sha256='+values['shared_sha256']+'\n')
    with (out/'build.log').open('x') as log:
        subprocess.run(['docker','build','-t',candidate,str(out)],check=True,stdout=log,stderr=subprocess.STDOUT)
    actual=read('docker','run','--rm','--network','none','--entrypoint','sha256sum',candidate,
                '/srv/dc/dc/GW/lib/com.app.common-mac-demo.jar','/srv/dc/dc/GW/lib/com.app.dc-mac-demo.jar')
    assert [x.split()[0] for x in actual.splitlines()]==[values['common_sha256'],values['shared_sha256']]
    proof={'base':base['Id'],'image':candidate,'guard_revision':revision,
           'common_sha256':values['common_sha256'],'shared_sha256':values['shared_sha256'],
           'gateway_source_classes_preserved':True,'workspace_gateway_changes_not_compiled':True}
    (out/'proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    print('gateway_IMAGE='+candidate+'\ngateway_guard_revision='+revision,flush=True)


if __name__=='__main__':
    main()
