#!/usr/bin/env python3
"""Read actual Order Primary pending matches, including financially unsettled fills."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import secrets
import subprocess

REPO=Path(__file__).resolve().parent.parent


def audit(transcripts, locations, max_age_seconds=30, max_replication_age_seconds=300):
    owners={}
    matched_partitions={location:set() for location in locations}
    coordinates=set()
    rows={location:{'financial_unsettled':0,'local_final_replication_pending':0,
                    'aged_financial_unsettled':0,'aged_local_final_replication_pending':0,
                    'oldest_pending_ms':0} for location in locations}
    for text in transcripts:
        for line in text.splitlines():
            fields=line.split('\t')
            if len(fields)<3 or fields[1] not in rows or not re.fullmatch(r'P[0-9]{3}',fields[2]):
                raise ValueError('Invalid complete cohort observation')
            kind,location,partition=fields[:3]
            if kind=='OWNER' and len(fields)==3:
                if location in owners:raise ValueError('Duplicate Primary observation')
                owners[location]=partition
            elif kind=='MATCH' and len(fields)==7 and fields[3] in ['true','false']:
                age,epoch,seq=map(int,fields[4:])
                if age<0 or epoch<2 or seq<1:raise ValueError('Invalid original match coordinate/age')
                coordinate=(partition,epoch,seq)
                if coordinate in coordinates:raise ValueError('Duplicate original match')
                coordinates.add(coordinate);matched_partitions[location].add(partition)
                confirmed=fields[3]=='true'
                key='local_final_replication_pending' if confirmed else 'financial_unsettled'
                rows[location][key]+=1
                if age>1000*(max_replication_age_seconds if confirmed else max_age_seconds):
                    rows[location]['aged_'+key]+=1
                rows[location]['oldest_pending_ms']=max(age,rows[location]['oldest_pending_ms'])
            else:raise ValueError('Unexpected observation row')
    if set(owners)!=set(locations):raise ValueError('Missing actual Primary cohort observation')
    if any(parts-{owners[location]} for location,parts in matched_partitions.items()):
        raise ValueError('Match differs from observed Primary partition')
    return {'passed':all(not x['aged_financial_unsettled'] and not x['aged_local_final_replication_pending']
                         for x in rows.values()),'locations':rows,'actual_primary_partitions':owners,
            'max_age_seconds':max_age_seconds,'max_replication_age_seconds':max_replication_age_seconds}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    parser.add_argument('--locations',nargs='+',required=True)
    parser.add_argument('--max-age-seconds',type=int,default=30)
    parser.add_argument('--max-replication-age-seconds',type=int,default=300)
    args=parser.parse_args()
    locations=sorted(args.locations)
    if (len(locations)!=len(set(locations)) or not 1<=len(locations)<=64
            or any(not re.fullmatch(r'[A-Z0-9]{6}',x) for x in locations)
            or min(args.max_age_seconds,args.max_replication_age_seconds)<=0):
        parser.error('A unique bounded cohort and positive age limits are required')
    root=args.root.resolve();work=root/('settlement-backlog-'+secrets.token_hex(4));work.mkdir(mode=0o700)
    cap=runpy.run_path(str(REPO/'scripts/verify-mac-demo-robot-capacity.py'))
    rpo=runpy.run_path(str(REPO/'scripts/verify-mac-demo-async-rpo.py'))
    release=cap['common_release_identity'](root);before=rpo['manifest'](root,'order')
    def run(*command):return subprocess.check_output(list(map(str,command)),text=True,timeout=90)
    java=Path(run('/usr/libexec/java_home','-v','1.8').strip())
    source=REPO/'tests/fixtures/async-rpo';agent='T554OrderCohortSettlementReadAgent'
    run(java/'bin/javac','-cp',java/'lib/tools.jar','-d',work,source/(agent+'.java'),source/'T554RpoAttach.java')
    manifest=work/'MANIFEST.MF';manifest.write_text('Manifest-Version: 1.0\nAgent-Class: '+agent+'\n\n')
    run(java/'bin/jar','cfm',work/'observer.jar',manifest,'-C',work,agent+'.class')
    transcripts=[];participants=[]
    for slot in ['a','b']:
        name=root.name+'-order-'+slot+'-hostready';container=json.loads(run('docker','inspect',name))[0]
        if not container['State']['Running']:raise RuntimeError('Order voter is not running')
        jar='/srv/dc/dc/OrderSvr/lib/com.app.common-mac-demo.jar'
        if run('docker','exec',name,'sha256sum',jar).split()[0]!=release['common_sha256']:
            raise RuntimeError('Actual Common differs from qualified release')
        remote='/tmp/'+work.name;run('docker','cp',work,name+':'+remote)
        run('docker','exec',name,'java','-cp','/opt/java/openjdk/lib/tools.jar:'+remote,
            'T554RpoAttach','1',remote+'/observer.jar',remote+'/rows.tsv,'+':'.join(locations))
        text=run('docker','exec',name,'cat',remote+'/rows.tsv');(work/(slot+'.tsv')).write_text(text)
        current=json.loads(run('docker','inspect',name))[0]
        if (current['Id'],current['State']['StartedAt'])!=(container['Id'],container['State']['StartedAt']):
            raise RuntimeError('Observed process changed during read')
        transcripts.append(text);participants.append({'name':name,'id':current['Id'],'started_at':current['State']['StartedAt']})
    if before!=rpo['manifest'](root,'order'):raise RuntimeError('Assignment changed during observation')
    report=audit(transcripts,locations,args.max_age_seconds,args.max_replication_age_seconds)
    report.update(scope='Read-only actual Primary Common-replayed Order pending index; independent financial cursor required',
                  at=datetime.now(timezone.utc).isoformat(),common_release=release,participants=participants,
                  agent_source_sha256=hashlib.sha256((source/(agent+'.java')).read_bytes()).hexdigest(),application_mutations=False)
    result=work/'proof.json';result.write_text(json.dumps(report,indent=2)+'\n')
    print(('PASS' if report['passed'] else 'NO_GO')+' '+str(result),flush=True)
    raise SystemExit(0 if report['passed'] else 2)


if __name__=='__main__':main()
