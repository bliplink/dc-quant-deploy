#!/usr/bin/env python3
"""Build a reviewed one-class notification fix over an exact verified Mac release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

CLASS='com.gateway.connector.tcp.server.AbstractApiProxy'
REL=Path('com/gateway/connector/tcp/server/AbstractApiProxy')


def run(*args, **kwargs):
    return subprocess.run([str(x) for x in args],check=True,**kwargs)


def read(*args):
    return subprocess.check_output([str(x) for x in args],text=True).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pairs(path):
    return dict(line.split('=',1) for line in path.read_text().splitlines() if line)


def instructions(text):
    methods={};key=None
    for line in text.splitlines():
        if re.match(r'^  (public|private|protected|static|[A-Za-z]).*[(].*[)];$',line):
            key=line.strip();methods[key]=[]
        elif key and re.match(r'^\s+\d+:',line):
            value=re.sub(r'^\s+\d+:\s*','',line)
            methods[key].append(re.sub(r'#\d+','#N',value))
    return methods


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('verified_build',type=Path)
    parser.add_argument('gateway_api_source',type=Path)
    parser.add_argument('new_build',type=Path)
    args=parser.parse_args()
    os.umask(0o077)
    original=args.verified_build.resolve(strict=True)
    source=args.gateway_api_source.resolve(strict=True)
    out=args.new_build.absolute()
    assert out.is_absolute() and not out.exists()
    assert read('uname','-s')=='Darwin' and read('docker','context','show')=='colima'
    assert not read('git','-C',source,'status','--porcelain','--untracked-files=no')
    revision=read('git','-C',source,'rev-parse','HEAD')
    images=pairs(original/'images.env')
    fresh=__import__('runpy').run_path(str(Path(__file__).with_name('mac-demo-fresh.py')))
    assert fresh['verified_common_release'](images)
    out.mkdir(mode=0o700)
    work=out/'notification-fanout';work.mkdir()
    base=read('docker','image','inspect','-f','{{.Id}}',images['order_IMAGE'])
    temporary=read('docker','create','--network','none','--entrypoint','/bin/true',base)
    try:
        run('docker','cp',temporary+':/srv/dc/dc/OrderSvr/lib',work/'lib',stdout=subprocess.DEVNULL)
    finally:
        run('docker','rm',temporary,stdout=subprocess.DEVNULL)
    libraries=work/'lib';gateways=list(libraries.glob('gateway-api-*.jar'));assert len(gateways)==1
    gateway=gateways[0]
    java=Path(read('/usr/libexec/java_home','-v','1.8'))
    classes=work/'classes';classes.mkdir()
    src=source/'gateway-api-java/gateway-api/src/main/java'/REL.with_suffix('.java')
    run(java/'bin/javac','-source','8','-target','8','-encoding','UTF-8','-cp',str(libraries/'*'),'-d',classes,src)
    # Replace exactly the outer class, preserving the original connector and
    # all existing anonymous classes. The public/private binary ABI is fixed.
    expected=classes/REL.with_suffix('.class');assert expected.is_file()
    for compiled in classes.rglob('*.class'):
        if compiled!=expected:compiled.unlink()
    before=read(java/'bin/javap','-p','-classpath',gateway,CLASS)
    after=read(java/'bin/javap','-p','-classpath',str(classes)+os.pathsep+str(libraries/'*'),CLASS)
    assert before==after,'Notification overlay changes connector ABI'
    before_code=instructions(read(java/'bin/javap','-c','-p','-classpath',gateway,CLASS))
    after_code=instructions(read(java/'bin/javap','-c','-p','-classpath',str(classes)+os.pathsep+str(libraries/'*'),CLASS))
    changed=[name for name in before_code.keys()|after_code.keys() if before_code.get(name)!=after_code.get(name)]
    assert changed==['public java.util.List<java.lang.String> notify(java.lang.String, byte[]);'],changed
    junit=Path.home()/'.m2/repository/junit/junit/4.13.2/junit-4.13.2.jar'
    hamcrest=Path.home()/'.m2/repository/org/hamcrest/hamcrest-core/1.3/hamcrest-core-1.3.jar'
    testroot=source/'gateway-api-java/gateway-api/src/test/java'
    # Other repository tests exercise client changes absent from the deployed
    # connector. Test this exact outer-class overlay with the original inner
    # classes and dependencies, in addition to the full source-repo suite.
    testfiles=sorted(testroot.rglob('AbstractApiProxy*Test.java'));assert len(testfiles)==2
    tests=work/'test-classes';tests.mkdir()
    classpath=os.pathsep.join([str(tests),str(classes),str(libraries/'*'),str(junit),str(hamcrest)])
    with (work/'test-compile.log').open('x') as log:
        run(java/'bin/javac','-source','8','-target','8','-encoding','UTF-8','-cp',classpath,'-d',tests,*testfiles,stdout=log,stderr=subprocess.STDOUT)
    names=[]
    for file in testfiles:
        if file.name.endswith('Test.java'):
            package=re.search(r'^package ([\w.]+);',file.read_text(),re.M);assert package
            names.append(package[1]+'.'+file.stem)
    with (work/'tests.log').open('x') as log:
        run(java/'bin/java','-Xms32m','-Xmx256m','-cp',classpath,'org.junit.runner.JUnitCore',*names,stdout=log,stderr=subprocess.STDOUT)
    assert 'OK (' in (work/'tests.log').read_text()
    compiled=digest(expected)
    proof={'gateway_api_revision':revision,'source_sha256':digest(src),'compiled_class_sha256':compiled,
           'original_gateway_jar_sha256':digest(gateway),'binary_abi_unchanged':True,
           'changed_methods':changed,
           'tests_passed_against_exact_deployed_dependencies':True,'exact_overlay_tests':3,
           'common_sha256':images['common_sha256'],'shared_sha256':images['shared_sha256'],'images':{}}
    for key,service,kind in [('order_IMAGE','OrderSvr','order'),('trade_IMAGE','TradeSvr','trade'),
                             ('md_IMAGE','MDSvr','md'),('gateway_IMAGE','GW','gateway')]:
        base_id=read('docker','image','inspect','-f','{{.Id}}',images[key])
        context=work/kind;target=context/'classes'/REL.with_suffix('.class');target.parent.mkdir(parents=True)
        shutil.copy2(expected,target)
        # An application class override, with the same Common/shared JARs.
        (context/'Dockerfile').write_text('FROM '+base_id+'\nCOPY classes/ /srv/dc/dc/'+service+'/classes/\n'
            +'LABEL dc.demo.recovery.base='+base_id+' dc.demo.recovery.'+kind+'.application.sha256='+compiled
            +' dc.demo.notification.fanout.source.revision='+revision+' dc.demo.notification.fanout.class.sha256='+compiled+'\n')
        # The base carries the application and exact dependency bytes. A class
        # hash alone would let a later build overwrite another release's tag.
        image='local/otc-mac-demo-'+kind+'-fanout:'+base_id.removeprefix('sha256:')[:12]+'-'+compiled[:12]
        with (context/'build.log').open('x') as log:
            run('docker','build','-t',image,context,stdout=log,stderr=subprocess.STDOUT)
        actual=read('docker','run','--rm','--network','none','--entrypoint','sha256sum',image,
            '/srv/dc/dc/'+service+'/classes/'+str(REL.with_suffix('.class')),
            '/srv/dc/dc/'+service+'/lib/com.app.common-mac-demo.jar',
            '/srv/dc/dc/'+service+'/lib/com.app.dc-mac-demo.jar',
            '/srv/dc/dc/'+service+'/lib/'+gateway.name)
        assert [row.split()[0] for row in actual.splitlines()]==[compiled,images['common_sha256'],images['shared_sha256'],digest(gateway)]
        proof['images'][kind]={'base':base_id,'image':image,'sha256':read('docker','image','inspect','-f','{{.Id}}',image)}
        images[key]=image
    images.update(notification_fanout_revision=revision,notification_fanout_class_sha256=compiled)
    (out/'images.env').write_text(''.join(key+'='+value+'\n' for key,value in images.items()))
    for name in ['order','trade','md','common','shared','common.jar','shared.jar']:
        (out/name).symlink_to(original/name,target_is_directory=(original/name).is_dir())
    (work/'proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    print('PASS '+str(out),flush=True)


if __name__=='__main__':
    main()
