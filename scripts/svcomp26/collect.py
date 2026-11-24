"""Download the ordinary C concurrency run sets and compare the published scores with raw BenchExec."""
import argparse
import bz2
import collections
import csv
from decimal import Decimal
import gzip
import hashlib
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path,PurePosixPath
import yaml

from config import TAG,TASKS
SITE='https://sv-comp.sosy-lab.org/2026/results/results-verified/'
API='https://gitlab.com/api/v4/projects/sosy-lab%2Fbenchmarking%2Fsv-benchmarks/repository/'
def dump(p,obj):p.write_bytes((json.dumps(obj,sort_keys=True,indent=2,ensure_ascii=False)+'\n').encode())
def hashb(b):return hashlib.sha256(b).hexdigest()
def get(url):
    req=urllib.request.Request(url,headers={'User-Agent':'SV-COMP-2026-concurrency-study'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=100) as res:return res.read()
def table(blob):
    d,_=json.JSONDecoder().raw_decode(blob.decode().split('const data = ',1)[1])
    k=next(k for k,t in enumerate(d['tools']) if t['tool']=='Deagle')
    return {row['id'][0]:row['results'][k] for row in d['rows']},d['tools'][k]
def rel(s):
    prefix='../sv-benchmarks/c/'
    if not s.startswith(prefix):raise ValueError(s)
    return s[len(prefix):]
def cols(r):return {c.get('title'):c.get('value') for c in r.findall('column')}
def band(s):
    t=Decimal(s)
    return 'lt1' if t<1 else '1to10' if t<10 else '10to300' if t<=300 else 'over300'
def main(cache,e):
    raw=e/'official';raw.mkdir(parents=True,exist_ok=True)
    def obtain(name,url,original=None):
        path=raw/name
        if not path.exists():path.write_bytes(original if original is not None else get(url))
        src[name]=dict(url=url,sha256=hashb(path.read_bytes()),bytes=path.stat().st_size)
        return path.read_bytes()
    src={};ids={};out=[];files={};verification=[]
    index=cache/'official-index.html'
    if not index.exists():index.write_bytes(get(SITE))
    links=sorted(set(re.findall(r'href="(deagle\.[^"]+\.Concurrency\.xml\.bz2\.fixed\.xml\.bz2)\.table\.html"',index.read_text(encoding='utf8'))))
    if not links:raise ValueError('no official Deagle ordinary concurrency run sets')
    info=obtain('svcomp26-tag.json',API+'tags/svcomp26',(cache/'tag.json').read_bytes() if (cache/'tag.json').exists() else None)
    assert json.loads(info)['commit']['id']==TAG
    for fixed in links:
        origin=fixed.removesuffix('.fixed.xml.bz2');category=origin.split('.results.SV-COMP26_',1)[1].split('.',1)[1].removesuffix('.xml.bz2')
        x=ET.fromstring(bz2.decompress(obtain(origin,SITE+origin)))
        f=ET.fromstring(bz2.decompress(obtain(fixed,SITE+fixed)))
        assert x.get('block')==category and x.get('tool')==f.get('tool')=='Deagle'
        pc=category.split('.')[1]; target=pc=='unreach-call'
        ids[category]=dict(raw=origin,scored=fixed,toolversion=x.get('version'),generator=x.get('generator'))
        scored={rel(r.get('name')):r for r in f.findall('run')}
        if target:
            pp=cache/'table.html'
            h=pp.read_bytes() if pp.exists() else get(SITE+category+'.table.html')
            (raw/'reach-table.html.gz').write_bytes(gzip.compress(h,compresslevel=6,mtime=0))
            src['reach-table.html.gz']=dict(url=SITE+category+'.table.html',uncompressed_sha256=hashb(h),sha256=hashb((raw/'reach-table.html.gz').read_bytes()))
            public,_=table(h)
            assert set(public)==set(scored)
        for row in x.findall('run'):
            task=rel(row.get('name'));s=cols(row);r=scored[task];t=cols(r)
            y=cache/'bench/c'/task
            registered=[rel(n.strip()) for n in row.get('files').strip('[]').split(',')]
            if not y.parent.is_dir():raise FileNotFoundError(y.parent)
            yb=y.read_bytes() if y.is_file() else None
            spec=yaml.safe_load(yb) if yb else {'properties':[]}
            name=spec.get('input_files',[]);names=[name] if isinstance(name,str) else name
            inputs=[(PurePosixPath(task).parent/n).as_posix() for n in names] if yb else registered
            if inputs!=registered:raise ValueError((task,inputs,registered))
            props=[p for p in spec['properties'] if PurePosixPath(p['property_file']).name==pc+'.prp']
            # Some official tasks were retracted between the run and the final tag.
            expected=props[0].get('expected_verdict') if len(props)==1 else None
            prop=rel(row.get('propertyFile'));files[task]=hashb(yb) if yb else None
            for n in [*inputs,prop]:
                path=cache/'bench/c'/n
                if n not in files:files[n]=hashb(path.read_bytes()) if path.is_file() else None
            cpu=s['cputime'].removesuffix('s');wall=s['walltime'].removesuffix('s');mem=int(s['memory'].removesuffix('B'))
            final=t['category'];score=None
            if target:
                z=public[task];v=z['values'];score=z['score']
                assert z['category']==final and v[0]['raw']==t['status'],task
                assert Decimal(v[3]['raw'])==Decimal(cpu) and Decimal(v[4]['raw'])==Decimal(wall) and Decimal(v[5]['raw'])*10**6==mem,task
            hit=expected is False and row.get('expectedVerdict')=='false' and s['status']==t['status']=='false('+pc+')' and s['category']=='correct' and final=='correct' and (not target or score==1)
            data=dict(category=category,task=task,yaml_sha256=files[task],input_files=','.join(inputs),input_sha256=','.join(files[n] or '' for n in inputs),
                  tag_status='missing_yaml_at_tag' if not yb else 'property_absent_at_tag' if not props else 'missing_input_at_tag' if any(not files[n] for n in inputs) else 'matched',
                  data_model=spec.get('options',{}).get('data_model'),property_path=prop,property_sha256=files[prop],yaml_expected=expected,
                  raw_expected=row.get('expectedVerdict'),raw_status=s['status'],raw_category=s['category'],official_status=t['status'],
                  official_category=final,official_score=score,cpu_s=cpu,wall_s=wall,memory_bytes=mem,
                  cpu_band=band(cpu),wall_band=band(wall),confirmed_false=hit)
            out.append(data)
    for name,(directory,_,_) in TASKS.items():
        y=cache/'bench/c'/directory/(name+'.yml');spec=yaml.safe_load(y.read_bytes());task=directory+'/'+y.name
        rows=[p for p in out if p['task']==task]
        verification.append(dict(task=task,tag=TAG,yaml_sha256=hashb(y.read_bytes()),properties=spec['properties'],official=rows))
    def write(name,rs):
        with (e/name).open('w',newline='',encoding='utf8') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(out[0]),lineterminator='\n');writer.writeheader();writer.writerows(rs)
    write('all-records.csv',out)
    confirmed=[r for r in out if r['category']=='C.unreach-call.Concurrency' and r['confirmed_false']]
    write('candidates.csv',sorted(confirmed,key=lambda r:(r['cpu_band']!='10to300',-Decimal(r['cpu_s']),r['task'])))
    write('unconfirmed.csv',[r for r in out if r['category']=='C.unreach-call.Concurrency' and r['official_category']=='correct-unconfirmed'])
    dump(e/'original-files.json',files);dump(e/'panel.json',verification)
    dump(e/'official-provenance.json',dict(svcomp26=TAG,tag_object=json.loads(info)['target'],sources=src,run_sets=ids,
        records=dict(collections.Counter(r['category'] for r in out)),confirmed_reach_bands=dict(collections.Counter(r['cpu_band'] for r in confirmed))))
    print(len(out),'rows;',len(files),'unique source, task and property hashes;',collections.Counter(r['cpu_band'] for r in confirmed))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('cache',type=Path);p.add_argument('evidence',type=Path);a=p.parse_args();main(a.cache,a.evidence)
