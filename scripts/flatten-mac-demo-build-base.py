#!/usr/bin/env python3
"""Materialize a deep local build base, preserving its complete image config."""
import argparse
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile


def inspect(image):
    return json.loads(subprocess.check_output(['docker','image','inspect',image],text=True))[0]


def digest(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(4*1024*1024),b''):result.update(chunk)
    return result.hexdigest()


def filesystem(path):
    result={}
    with tarfile.open(path,'r:') as archive:
        for member in archive:
            content=None
            if member.isfile():
                value=hashlib.sha256()
                stream=archive.extractfile(member)
                for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
                content=value.hexdigest()
            result[member.name]=(member.type.decode('ascii'),member.mode,member.uid,member.gid,
                member.linkname,member.devmajor,member.devminor,content,member.pax_headers)
    return result


def export(image,path):
    container=subprocess.check_output(['docker','create','--network','none','--entrypoint','/bin/true',image],text=True).strip()
    try:subprocess.run(['docker','export','-o',str(path),container],check=True)
    finally:subprocess.run(['docker','rm','-v',container],check=True,stdout=subprocess.DEVNULL)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    parser.add_argument('cache',type=Path)
    args=parser.parse_args()
    original=inspect(args.image)
    if original['Os']!='linux' or original['Config'].get('Volumes'):
        raise ValueError('Build-base materialization requires a Linux image without declared volumes')
    identity=original['Id']
    if len(original['RootFS']['Layers'])<96:
        print(identity)
        return
    os.umask(0o077)
    folder=args.cache.resolve()/identity.split(':',1)[1]
    folder.mkdir(parents=True,exist_ok=True)
    with (folder/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        proof=folder/'verified.json'
        if proof.exists():
            saved=json.loads(proof.read_text())
            try:current=inspect(saved['image'])
            except subprocess.CalledProcessError:current=None
            if (current is not None and saved['source']==identity and current['Id']==saved['image_id']
                    and current['Config']==original['Config']
                    and current['RootFS']['Layers']==['sha256:'+saved['layer_sha256']]):
                print(current['Id'])
                return
            if current is not None:
                raise ValueError('Cached flattened image differs from its verified source/configuration')
        layer=folder/'filesystem.tar'
        export(identity,layer)
        layer_hash=digest(layer)
        config={'architecture':original['Architecture'],'os':original['Os'],
            'created':original['Created'],'config':original['Config'],
            'rootfs':{'type':'layers','diff_ids':['sha256:'+layer_hash]},
            'history':[{'created':original['Created'],'created_by':'T554 materialized build base '+identity}]}
        encoded=json.dumps(config,sort_keys=True,separators=(',',':')).encode()
        config_hash=hashlib.sha256(encoded).hexdigest()
        image='local/otc-mac-demo-flat-base:'+identity.split(':',1)[1][:20]
        manifest=[{'Config':config_hash+'.json','RepoTags':[image],'Layers':[layer_hash+'/layer.tar']}]
        packed=folder/'docker-load.tar'
        with tarfile.open(packed,'w',format=tarfile.PAX_FORMAT) as archive:
            for name,data in [(config_hash+'.json',encoded),('manifest.json',json.dumps(manifest).encode())]:
                entry=tarfile.TarInfo(name)
                entry.size=len(data)
                archive.addfile(entry,io.BytesIO(data))
            archive.add(layer,arcname=layer_hash+'/layer.tar',recursive=False)
        with (folder/'load.log').open('w') as log:
            subprocess.run(['docker','load','-i',str(packed)],stdout=log,stderr=subprocess.STDOUT,check=True)
        loaded=inspect(image)
        if (loaded['Config']!=original['Config']
                or loaded['Architecture']!=original['Architecture']
                or loaded['RootFS']['Layers']!=['sha256:'+layer_hash]):
            raise ValueError('Materialized build base changed its runtime configuration')
        checked=folder/'verified-filesystem.tar'
        export(image,checked)
        before,after=filesystem(layer),filesystem(checked)
        if before!=after:
            differences=sorted(key for key in before.keys()|after.keys() if before.get(key)!=after.get(key))
            (folder/'filesystem-differences.json').write_text(json.dumps(differences,indent=2)+'\n')
            raise ValueError('Materialized build base filesystem differs from its source')
        record={'source':identity,'source_layer_count':len(original['RootFS']['Layers']),
            'image':image,'image_id':loaded['Id'],'layer_sha256':layer_hash,
            'docker_load_config_sha256':config_hash,
            'runtime_config_equal':True,'complete_filesystem_equal':True,'filesystem_entries':len(before)}
        staged=folder/'verified.tmp'
        staged.write_text(json.dumps(record,indent=2)+'\n')
        staged.replace(proof)
        packed.unlink()
        checked.unlink()
        layer.unlink()
        print(loaded['Id'])


if __name__=='__main__':main()
