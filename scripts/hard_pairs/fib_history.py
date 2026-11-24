"""Freeze the upstream race repair at its actual parent and child, including publication YAML and preprocessed units."""
import concurrent.futures
import json
import urllib.parse
from pathlib import Path
from history25 import API,get
from prepare import E,ROOT,REPO,dump,h,job,schedule,PROPERTY
import yaml
PARENT='de30d1d37df637a9f45a8fcefce8816bb1372f00'
FIX='5110fee06e4466b05ac4ffab744e1f57ef498b37'
FAMILY='fib_safe'
SIZES=(10,11,12)
PREFIX='fib-history'
WAVE='history'
def download():
    root=E/'historical-fib'
    def fetch(arg):
        tag,file=arg;url=API+'files/'+urllib.parse.quote('c/'+file,safe='')+'/raw?ref='+tag
        p=root/tag/file;p.parent.mkdir(parents=True,exist_ok=True)
        if not p.is_file():p.write_bytes(get(url,45))
        return {'commit':tag,'path':'c/'+file,'url':url,'sha256':h(p.read_bytes())}
    paths=['pthread/'+FAMILY+'.h','properties/unreach-call.prp']
    for n in SIZES:
        paths.extend('pthread/'+FAMILY+'-'+str(n)+suffix for suffix in ('.c','.i','.yml'))
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        rows=list(pool.map(fetch,[(t,k) for t in (PARENT,FIX) for k in paths]))
    name='receipts.json' if FAMILY=='fib_safe' else ('fib_unsafe-receipts.json' if FIX.startswith('11e0dee8') else FAMILY+'-'+FIX[:8]+'-receipts.json')
    dump(root/name,rows)
def plan():
    cases=json.loads((E/'inventory.json').read_bytes())
    jobs=[]
    for n in SIZES:
        for number,commit in enumerate((PARENT,FIX)):
            root=E/'historical-fib'/commit
            y=root/'pthread'/(FAMILY+'-'+str(n)+'.yml')
            spec=yaml.safe_load(y.read_bytes());src=y.parent/spec['input_files']
            prop=next(p for p in spec['properties'] if p['property_file'].endswith('/unreach-call.prp'))
            assert h((y.parent/prop['property_file']).read_bytes())==PROPERTY
            key=f'{PREFIX}{n}-{number}';out=ROOT/'inputs'/key;out.mkdir(exist_ok=True,parents=True)
            (out/'i').write_bytes(src.read_bytes());(out/'task.yml').write_bytes(y.read_bytes())
            c=cases[key]=dict(id=key,task='pthread/'+y.name,source='SVBENCH_HISTORY',original=src.name,model=spec['options']['data_model'],
                expected_original=prop['expected_verdict'],bound=2*n+3,sha256=h(src.read_bytes()),yaml_sha256=h(y.read_bytes()),
                public_sha256=h(src.read_bytes()),property_sha256=PROPERTY,official=None,file=(out/'i').relative_to(ROOT).as_posix(),
                override=None,upstream_commit=commit)
            jobs.append(job(c,WAVE,300,4))
    dump(E/'inventory.json',cases);dump(ROOT/(WAVE+'.json'),jobs);schedule([(WAVE,8)])
if __name__=='__main__':
    import sys
    if 'unsafe' in sys.argv:
        FAMILY='fib_unsafe';SIZES=(12,);PREFIX='fib-racy';WAVE='racyhistory'
        PARENT='324a403add1f08e53a6b59a8ce1ee019bbd17da4';FIX='11e0dee8d6f15a4d6f4069885a3b94a9c89039cc'
        if 'restored' in sys.argv:FIX='30b58c811fa1c87ed9a5103c81bb35bc1bbc2dc3'
        elif sys.argv[1]=='plan':raise ValueError('intermediate revision weakens the source assertion')
    (download if sys.argv[1]=='download' else plan)()
