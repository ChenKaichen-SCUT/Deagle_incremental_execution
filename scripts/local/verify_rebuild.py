"""Check all six source-built front-end answers and exercise the rebuilt worker on the complete inputs."""
import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from restore import PROJECT, sha


def verify(tree,smoke,output):
    import sys
    sys.path.insert(0,str(PROJECT/'scripts/stage11c'))
    from negative import worker
    output.mkdir(parents=True,exist_ok=False)
    exe=tree/'src/cbmc/deagle_exe'
    binary=tree/'local-build/worker'
    rows=[]
    for case in ('fib_updates_8','lock12','ticket56-reviewed'):
        pair=smoke/'formal'/case/'1/TC'
        local=[]
        for side in ('old','new'):
            ref=pair/side
            receipt=json.loads((ref/'receipt.json').read_bytes())
            wd=output/case/side
            wd.mkdir(parents=True)
            (wd/'worker').mkdir()
            for name,h in receipt['source'].items():
                shutil.copyfile(ref/name,wd/name)
                assert sha(wd/name)==h
            env=dict(PATH=os.environ['PATH'],LC_ALL='C',INCDEAGLE_JSON_OUTPUT=str(wd/'result.json'),
                     S8_STREAM='1',S8_OUT=str(wd),S10_DIR=str(wd),INCDEAGLE_OBSERVE_DIR=str(wd))
            with (wd/'stdout').open('wb') as log,(wd/'stderr').open('wb') as err:
                run=subprocess.run([exe,*receipt['argv']],cwd=wd,env=env,stdout=log,stderr=err,timeout=120)
            props=[[r['property'],r['status']] for o in json.loads((wd/'result.json').read_bytes()) for r in o.get('result',[])]
            assert run.returncode==receipt['exit'] and props==[p[:2] for p in receipt['properties']]
            assert sha(wd/'s8-input.bin')==sha(ref/'s8-input.bin') and sha(wd/'s8-graph.tsv')==sha(ref/'s8-graph.tsv')
            for n in ('events.tsv','plan.txt','approved.tsv'):
                if (ref/n).exists():shutil.copyfile(ref/n,wd/n)
            row=dict(case=case,side=side,properties=props,exit=run.returncode,
                     stream_sha256=sha(wd/'s8-input.bin'),graph_sha256=sha(wd/'s8-graph.tsv'))
            rows.append(row);local.append(wd)
        current=local[1]
        seal='C11v1 '+' '.join(sha(current/n) for n in ('s8-input.bin','s8-graph.tsv','approved.tsv'))
        rc,_=worker(binary,'TC',local,output/case,seal)
        assert rc==0
        for d,row in zip(local,rows[-2:]):
            ref=pair/d.name
            for n in ('answer.txt','worker/search.bin','worker/use.tsv'):
                assert sha(d/n)==sha(ref/n),(case,d.name,n)
            row['search_sha256']=sha(d/'worker/search.bin')
            row['answer_sha256']=sha(d/'answer.txt')
            row['use_sha256']=sha(d/'worker/use.tsv')
        print(case,'both fresh model streams, answers and worker searches matched',flush=True)
    data=dict(source_commit=subprocess.check_output(['git','-C',tree,'rev-parse','HEAD'],text=True).strip(),
              frontend_sha256=sha(exe),worker_sha256=sha(binary),runs=rows)
    (output/'receipt.json').write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    for k in ('tree','smoke','output'):ap.add_argument(k,type=Path)
    a=ap.parse_args();verify(a.tree.resolve(),a.smoke.resolve(),a.output.resolve())
