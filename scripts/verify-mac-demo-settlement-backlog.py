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


def audit_all_partitions(transcripts, locations, manifest, max_age_seconds=30,
                         max_replication_age_seconds=300):
    expected={'P%03d'%index for index in range(256)}
    if set(manifest)!=expected:
        raise ValueError('Complete actual partition manifest required')
    owners={}; matches=[]; retained=[]; coordinates=set()
    for text in transcripts:
        local_parts=set(); local_matches=[]
        for line in text.splitlines():
            fields=line.split('\t')
            if len(fields)==4 and fields[0]=='PARTITION_OWNER':
                _,partition,node,epoch=fields
                if (partition not in manifest or partition in owners
                        or node!=manifest[partition]['primary']
                        or int(epoch)!=manifest[partition]['epoch']):
                    raise ValueError('Wrong, stale or duplicate actual partition owner')
                owners[partition]=node
                local_parts.add(partition)
            elif len(fields)==7 and fields[0] in ('MATCH','ORDER_ONLY_RETAINED'):
                local_matches.append(line)
            else:
                raise ValueError('Invalid complete all-symbol observation')
        if any(line.split('\t')[2] not in local_parts for line in local_matches):
            raise ValueError('Match was not read from its actual Primary')
        for line in local_matches:
            fields=line.split('\t');key=(fields[2],int(fields[5]),int(fields[6]))
            if key in coordinates:
                raise ValueError('Duplicate original match coordinate')
            coordinates.add(key)
            if fields[0]=='ORDER_ONLY_RETAINED':
                location,partition,symbol=fields[1:4];age,epoch,seq=map(int,fields[4:])
                if (location not in locations or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',symbol)
                        or age<0 or epoch<2 or seq<1):
                    raise ValueError('Invalid retained order-only delivery')
                retained.append(dict(location=location,partition=partition,symbol=symbol,
                                     age_ms=age,epoch=epoch,sequence=seq))
            else:
                matches.append(line)
    if set(owners)!=expected:
        raise ValueError('Missing actual Primary partition observation')
    # Reuse the existing exact match-coordinate and age validation per shard.
    totals={location:{'financial_unsettled':0,'local_final_replication_pending':0,
                      'aged_financial_unsettled':0,'aged_local_final_replication_pending':0,
                      'oldest_pending_ms':0} for location in locations}
    by_partition={partition:[] for partition in expected}
    for line in matches:
        fields=line.split('\t')
        if fields[1] not in totals or fields[2] not in by_partition:
            raise ValueError('Match is outside declared cohort or physical partitions')
        by_partition[fields[2]].append(line)
    for partition,lines in by_partition.items():
        transcript='\n'.join(lines+['OWNER\t'+location+'\t'+partition for location in locations])+'\n'
        part=audit([transcript],locations,max_age_seconds,max_replication_age_seconds)
        for location,counts in part['locations'].items():
            for key,value in counts.items():
                totals[location][key]=(max(totals[location][key],value)
                                       if key=='oldest_pending_ms' else totals[location][key]+value)
    return {'passed':all(not row['aged_financial_unsettled'] and not row['aged_local_final_replication_pending']
                         for row in totals.values()),'locations':totals,
            'actual_primary_partition_owners':dict(sorted(owners.items())),
            'all_symbols_covered':True,'observed_primary_partitions':len(owners),
            'order_only_retained_delivery_records':retained,
            'all_business_delivery_records_retired':not matches and not retained,
            'passed_scope':'Trade financial settlement and final-copy backlog age; retained ORDER_ONLY replay records listed separately',
            'max_age_seconds':max_age_seconds,'max_replication_age_seconds':max_replication_age_seconds}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    parser.add_argument('--locations',nargs='+',required=True)
    parser.add_argument('--max-age-seconds',type=int,default=30)
    parser.add_argument('--max-replication-age-seconds',type=int,default=300)
    parser.add_argument('--all-symbols',action='store_true',
                        help='Observe all 256 actual Primary partitions, including custom products')
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
    source=REPO/'tests/fixtures/async-rpo'
    template=('T554OrderAllPartitionsSettlementReadAgent' if args.all_symbols
              else 'T554OrderCohortSettlementReadAgent')
    original=(source/(template+'.java')).read_bytes()
    source_sha=hashlib.sha256(original).hexdigest()
    # Instrumentation can reuse an already loaded agent class after its JAR
    # changes. Bind the binary name to the exact template on every attach.
    agent=template+'_'+source_sha[:24]
    generated=original.decode().replace('public final class '+template+' {',
            'public final class '+agent+' {\n'
            '    private static final String OBSERVER_SOURCE="'+source_sha+'";',1)
    marker='StringBuilder result=new StringBuilder();'
    if marker not in generated or 'public final class '+agent+' {' not in generated:
        raise RuntimeError('Expected explicit observer transcript builder')
    generated=generated.replace(marker,
            'StringBuilder result=new StringBuilder("OBSERVER_SOURCE\\t"+OBSERVER_SOURCE+"\\n");',1)
    generated_source=work/(agent+'.java');generated_source.write_text(generated)
    run(java/'bin/javac','-cp',java/'lib/tools.jar','-d',work,generated_source,source/'T554RpoAttach.java')
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
        lines=text.splitlines()
        if not lines or lines[0]!='OBSERVER_SOURCE\t'+source_sha:
            raise RuntimeError('Loaded observer did not report the exact source version')
        current=json.loads(run('docker','inspect',name))[0]
        if (current['Id'],current['State']['StartedAt'])!=(container['Id'],container['State']['StartedAt']):
            raise RuntimeError('Observed process changed during read')
        transcripts.append('\n'.join(lines[1:]));participants.append({'name':name,'id':current['Id'],'started_at':current['State']['StartedAt']})
    if before!=rpo['manifest'](root,'order'):raise RuntimeError('Assignment changed during observation')
    report=(audit_all_partitions(transcripts,locations,before,args.max_age_seconds,args.max_replication_age_seconds)
            if args.all_symbols else audit(transcripts,locations,args.max_age_seconds,args.max_replication_age_seconds))
    report.update(scope='Read-only actual Primary Common-replayed Order pending index; independent financial cursor required',
                  at=datetime.now(timezone.utc).isoformat(),common_release=release,participants=participants,
                  agent_source_sha256=source_sha,observer_class_name=agent,
                  observer_class_sha256=hashlib.sha256((work/(agent+'.class')).read_bytes()).hexdigest(),
                  generated_observer_source_sha256=hashlib.sha256(generated_source.read_bytes()).hexdigest(),
                  application_mutations=False)
    result=work/'proof.json';result.write_text(json.dumps(report,indent=2)+'\n')
    print(('PASS' if report['passed'] else 'NO_GO')+' '+str(result),flush=True)
    raise SystemExit(0 if report['passed'] else 2)


if __name__=='__main__':main()
