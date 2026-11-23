"""Lossless content-addressed archive for measurements, profiles and controlled replays."""
import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import zipfile
from pathlib import Path,PurePosixPath

ROOTS=('formal','pilot','build','old-controls','frontend','frontend-traced','frontend-setup','side','structural','micro','audit','replay')
LOGS=('formal.log','pilot.log','build-console.log','old-controls.log','strace-frontend.txt','side.log','micro.log','replay.log','setup.log')
PART=14*1024**2
CHUNK=4*1024**2

def sha(data):return hashlib.sha256(data).hexdigest()
def valid(name):
    p=PurePosixPath(name)
    return (str(p)==name and p.parts and not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name
            and p.parts[0] in (*ROOTS,*LOGS) and not any(v.lower() in ('.git','.env','apikey.txt','.ssh','credentials') for v in p.parts))

def pack(source,dest):
    dest.mkdir(parents=True,exist_ok=True)
    seen={}
    files={}
    content={}
    archives={}
    zipped=None
    paths=sorted([p for root in ROOTS for p in (source/root).rglob('*') if p.is_file()]+[source/p for p in LOGS if (source/p).is_file()])
    for path in paths:
        name=path.relative_to(source).as_posix()
        if not valid(name) or path.is_symlink():raise ValueError(name)
        # The verifier, codec and compiler have public provenance via the native
        # patch/build receipt. Their executables are not measurement outputs.
        if path.name in ('cache-codec','solver-replay'):continue
        if '__pycache__' in path.parts:continue
        h=hashlib.sha256()
        chunks=[]
        size=0
        with path.open('rb') as f:
            while True:
                data=f.read(CHUNK)
                if not data:break
                size+=len(data);h.update(data);key=sha(data);chunks.append(key)
                if key in seen:continue
                payload=gzip.compress(data,compresslevel=5,mtime=0)
                if zipped is None or zipped.fp.tell()+len(payload)+150>PART:
                    if zipped:zipped.close()
                    packname=f'raw-{len(archives)+1:03}.zip'
                    zipped=zipfile.ZipFile(dest/packname,'w',compression=zipfile.ZIP_STORED)
                    archives[packname]=None
                zipped.writestr(zipfile.ZipInfo(key+'.gz',date_time=(1980,1,1,0,0,0)),payload)
                seen[key]=packname
        fingerprint=h.hexdigest()
        files[name]=fingerprint
        content[fingerprint]=[size,*chunks]
    if zipped:zipped.close()
    for name in archives:
        blob=(dest/name).read_bytes();archives[name]={'bytes':len(blob),'sha256':sha(blob)}
    doc=dict(schema=1,files=files,contents=content,chunks=seen,archives=archives)
    raw=(json.dumps(doc,sort_keys=True,separators=(',',':'))+'\n').encode()
    (dest/'raw-index.json.gz').write_bytes(gzip.compress(raw,compresslevel=6,mtime=0))
    print('Archived',len(files),'paths',len(content),'distinct payloads',len(seen),'chunks',len(archives),'parts',
          sum(x['bytes'] for x in archives.values()),'bytes',flush=True)
    return doc

def limited(name):
    # Include formal inputs for exact numeric reconstruction and each side probe's
    # original outputs. Full restore also materializes snapshots, IREP and compiler logs.
    if not name.startswith('formal/'):return not name.startswith('pilot/')
    last=name.rsplit('/',1)[-1]
    return last in ('plan.json','settings.json','complete.json','service.json','samples.json.gz','measurement.json',
                    'diagnostic.stdout','result.json','session.json','fragments.irep','goto.irep','lemma-cache.json',
                    's8-native.tsv','s8-search.tsv','s8-graph.tsv','s8-sat.tsv','s8-trace.tsv','s8-gcc.jsonl','s8-binder.json',
                    'native-stats.json','native-import.json','native-plan.json','theory-validation.json','full_model.json',
                    'raw_ssa.json','sc_input.json','goto.json','cex0.json','cex1.json','program.c','harness.c','verdict.json',
                    'gamma.json','phi.json','theory-summary.json','visits.json','native-bindings.json','manifest.json',
                    'theory-settings.json','theory-context.json','theory-export.json','native-conflicts.jsonl')

def unpack(evidence,dest,full=False):
    doc=json.loads(gzip.decompress((evidence/'raw-index.json.gz').read_bytes()))
    objects=dest/'.s8-objects'
    objects.mkdir(parents=True,exist_ok=True)
    seen=set()
    for name,r in doc['archives'].items():
        if not re.fullmatch(r'raw-[0-9]+\.zip',name):raise ValueError(name)
        p=evidence/name
        if not (p.stat().st_size==r['bytes'] and sha(p.read_bytes())==r['sha256']):raise ValueError(name)
        with zipfile.ZipFile(p) as z:
            for entry in z.infolist():
                key=entry.filename[:-3]
                if not re.fullmatch('[0-9a-f]{64}',key) or key in seen or doc['chunks'].get(key)!=name or entry.filename!=key+'.gz':raise ValueError(entry.filename)
                payload=gzip.decompress(z.read(entry))
                if sha(payload)!=key:raise ValueError(key)
                (objects/key).write_bytes(payload);seen.add(key)
    if seen!=set(doc['chunks']):raise ValueError('Missing chunks')
    if set(doc['contents'])!=set(doc['files'].values()):raise ValueError('Unreferenced or missing payload')
    for key,desc in doc['contents'].items():
        h=hashlib.sha256();size=0
        for c in desc[1:]:
            if c not in seen:raise ValueError('Unknown chunk')
            b=(objects/c).read_bytes();size+=len(b);h.update(b)
        if (h.hexdigest(),size)!=(key,desc[0]):raise ValueError(key)
    for name,key in doc['files'].items():
        if not valid(name) or key not in doc['contents']:raise ValueError(name)
        if not(full or limited(name)):continue
        p=dest.joinpath(*PurePosixPath(name).parts)
        p.parent.mkdir(exist_ok=True,parents=True)
        if p.exists():raise ValueError('Use a fresh restore directory: '+str(p))
        pieces=doc['contents'][key][1:]
        if len(pieces)==1:
            try:os.link(objects/pieces[0],p)
            except OSError:shutil.copyfile(objects/pieces[0],p)
        else:
            with p.open('wb') as out:
                for c in pieces:out.write((objects/c).read_bytes())
    return doc

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('operation',choices=['pack','unpack'])
    p.add_argument('source',type=Path);p.add_argument('destination',type=Path);p.add_argument('--full',action='store_true')
    a=p.parse_args()
    if a.operation=='pack':pack(a.source,a.destination)
    else:unpack(a.source,a.destination,a.full)
