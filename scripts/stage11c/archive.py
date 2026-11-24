"""Freeze the complete raw evidence, deduplicating logical paths by the hash of their original bytes."""
import collections,gzip,hashlib,json,shutil,sys,zipfile
from pathlib import Path
from audit import read,save,digest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/stage11b'))
from witness import result
from raw_store import split
def collect(run,out):
    out.mkdir(exist_ok=True,parents=True);raw=out/'raw';raw.mkdir(exist_ok=True)
    files={};unique=set();rows=[];witnesses={};contracts={};prereg={}
    archive=run/'11c-raw.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=5) as z:
        def keep(p,k):
            if not p.is_file():return
            v=p.read_bytes();s=hashlib.sha256(v).hexdigest();files[k]=s
            if s not in unique:
                unique.add(s);info=zipfile.ZipInfo(s);info.compress_type=zipfile.ZIP_DEFLATED;z.writestr(info,v)
        for path in sorted((run/'formal').glob('*/*/*/pair.json')):
            pair=read(path);d=path.parent;rec=[]
            for side in ('old','new'):
                sub=d/side;r=read(sub/'receipt.json');r['memory']=read(sub/'controller-memory.json') if (sub/'controller-memory.json').exists() else None
                for name in ('capture-time','review-time','refused','gate'):
                    if (sub/(name+'.json')).exists():r[name]=read(sub/(name+'.json'))
                if pair['mode']!='stock' and r['exit']==10:
                    ident=(r['source'].get('program.c') or r['source']['program.i'])+'-'+digest(sub/'answer.txt')
                    if ident not in witnesses:witnesses[ident]=result(sub)
                    assert witnesses[ident]['status']=='EXPLICIT_SC_ORDER';r['witness']=ident
                rec.append(r)
            rows.append(dict(**pair,sides=rec))
            for p in d.rglob('*'):
                if p.is_file():keep(p,p.relative_to(run).as_posix())
        for folder in ('controls','mechanism'):
            for p in sorted((run/folder).rglob('*')):
                if not p.is_file():continue
                keep(p,p.relative_to(run).as_posix())
        for n in ('build.log','build.sha256'):keep(run/'build'/n,'build/'+n)
        for n in ('build.log','build.sha256'):keep(run/'audit-build'/n,'lifecycle-build/'+n)
        for p in (run/'lifecycle').glob('*/*/*/worker/stats.tsv'):keep(p,p.relative_to(run).as_posix())
        for n in ('formal.log','extra.log','done','extra-done'):keep(run/n,n)
        # The earlier recording/transport design is kept as exploratory evidence, outside all timing comparisons.
        first=run.parent/'stage-11c'
        for n in ('done','formal.log','startup-failure.log'):keep(first/n,'pilot/'+n)
        for p in sorted((first/'formal').glob('*/1/*/new/worker/use.tsv')):
            keep(p,'pilot/'+p.relative_to(first).as_posix())
    split(archive,raw,6*1024*1024);save(raw,'files.json',files)
    save(out,'trials.json',rows);save(out,'witnesses.json',witnesses)
    for src,name in [(run/'build/src/native.patch','native.patch'),(run/'build/build.sha256','build.sha256'),
                     (run/'controls/negative/negative.json','negative.json'),(run/'controls/negative/co-directions.tsv','co-directions.tsv'),
                     (run/'controls/host.txt','host.txt'),(run/'lifecycle/counts.json','lifecycle.json')]:
        shutil.copyfile(src,out/name)
    records={v:read(run/'controls/multiquery'/v/'receipt.json') for v in ('P0','P1')}
    save(out,'multiquery.json',records)
    print(len(rows),'pairs,',len(files),'raw paths,',len(unique),'objects,',archive.stat().st_size,'ZIP bytes')
if __name__=='__main__':collect(*map(Path,sys.argv[1:]))
