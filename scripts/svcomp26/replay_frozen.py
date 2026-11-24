"""Run the four frozen adjacent pairs in a fresh directory without a model provider or credentials."""
import argparse
import shutil
from pathlib import Path
from config import DEAGLE,WORKER,ROOT,TASKS,folder
from oracle import read,run,sha,metadata
from functional import run as functional
from compare import main as compare
def replay(recorded,out,exe,driver):
    assert sha(exe)==DEAGLE and sha(driver)==WORKER
    out.mkdir(parents=True,exist_ok=False)
    for case in sorted((ROOT/'cases/svcomp26/versions').iterdir()):
        task=case.name;src=folder(task)/metadata(task)['input']
        run(task,exe,out/'P0'/task);functional(task,src,out/'functional'/task/'P0')
        for ver in sorted(case.iterdir()):
            rnum=int(ver.name[1:]);dst=out/'rounds'/task/ver.name;dst.mkdir(parents=True)
            receipt=recorded/'rounds'/task/ver.name/'model.json';locked=read(receipt)
            assert locked['status']=='FROZEN' and sha(ver/'program.i')==locked['candidate_sha256'] and sha(ver/'repair.patch')==locked['patch_sha256']
            shutil.copyfile(receipt,dst/'model.json');shutil.copyfile(ver/'program.i',dst/'candidate.i')
            run(task,exe,out/'oracles'/task/ver.name,source=dst/'candidate.i')
            functional(task,dst/'candidate.i',out/'functional'/task/ver.name)
            compare(out,exe,driver,task,rnum,3)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('recorded','out','exe','driver'):p.add_argument(k,type=Path)
    a=p.parse_args();replay(*(getattr(a,k).resolve() for k in ('recorded','out','exe','driver')))
