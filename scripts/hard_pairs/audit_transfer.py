"""Verify every raw file in the offline server archive; restore the publishable evidence subset."""
import argparse
import hashlib
import json
import tarfile
from pathlib import Path,PurePosixPath
from prepare import E,dump
SMALL={'result.json','stdout','stderr','s8-search.tsv','s8-native.tsv','s8-sat.tsv','native-state.tsv','boundary.tsv'}

def verify(full,output):
    output.mkdir(parents=True,exist_ok=True)
    whole=hashlib.sha256()
    with full.open('rb') as f:
        for b in iter(lambda:f.read(4<<20),b''):whole.update(b)
    pending={};expect={};raw_files=raw_bytes=0;sizes={};done=set();complete=[];orders=[]
    with tarfile.open(full,mode='r|gz') as t:
        for member in t:
            name=member.name;rel=PurePosixPath(name)
            if (rel.is_absolute() or '..' in rel.parts or '\\' in name or not member.isfile()):raise ValueError('unsafe file '+name)
            if name in done:raise ValueError('duplicate archive path '+name)
            done.add(name)
            src=t.extractfile(member)
            if len(rel.parts)==1 or rel.name=='receipt.json' and len(rel.parts)==3:
                blob=src.read();dest=output/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(blob)
                if rel.name=='receipt.json':
                    r=json.loads(blob);key='/'.join(rel.parts[:2]);assert r['out']==key
                    prefix=key+'/'+r['attempt']+'/';pending.update({prefix+k:v for k,v in r['raw_sha256'].items()});expect[key]=r['phase']
                elif name.startswith('order-') and name.endswith('.complete'):complete.append(name)
                elif name.startswith('order-') and name.endswith('.txt'):orders.append(name)
                continue
            if len(rel.parts)!=4 or name not in pending:raise ValueError('raw member without receipt '+name)
            mode=expect['/'.join(rel.parts[:2])]
            keep=mode.startswith('formal') or rel.name in SMALL
            dest=output/name;fp=None
            if keep:
                dest.parent.mkdir(parents=True,exist_ok=True);fp=dest.open('wb')
            H=hashlib.sha256()
            try:
                for b in iter(lambda:src.read(2<<20),b''):
                    H.update(b)
                    if fp:fp.write(b)
            finally:
                if fp:fp.close()
            if H.hexdigest()!=pending.pop(name):raise ValueError('server member SHA mismatch '+name)
            raw_files+=1;raw_bytes+=member.size;sizes[mode]=sizes.get(mode,0)+member.size
    assert not pending and set(p+'.complete' for p in orders)==set(complete)
    receipt=dict(archive=full.name,bytes=full.stat().st_size,sha256=whole.hexdigest(),server_attempts=len(expect),verified_raw_files=raw_files,
                 verified_uncompressed_raw_bytes=raw_bytes,raw_bytes_per_phase=sizes,completed_dispatches=sorted(complete),local_path='runs/hard-pairs-admin/'+full.name)
    dump(E/'transfer.json',receipt);print(json.dumps(receipt,indent=2))
if __name__=='__main__':
    import sys
    verify(*map(Path,sys.argv[1:]))
