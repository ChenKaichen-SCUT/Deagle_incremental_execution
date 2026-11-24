"""Native independent all-property verification before any solver comparison."""
import argparse
from pathlib import Path
from config import DEAGLE,TASKS,folder
from oracle import metadata,run,read,save,sha
from functional import run as probe
from compare import main as compare

def main(root,exe,driver,roundno,mode):
    assert sha(exe)==DEAGLE
    for task in TASKS:
        p=root/'rounds'/task/f'P{roundno}';model=p/'model.json'
        if not model.is_file():continue
        old=folder(task)/metadata(task)['input'] if roundno==1 else root/'rounds'/task/f'P{roundno-1}/candidate.i'
        if mode=='oracle' and roundno==1 and not (root/'functional'/task/'P0').exists():
            probe(task,old,root/'functional'/task/'P0')
        if read(model)['status']!='FROZEN':continue
        new=p/'candidate.i';assert sha(new)==read(model)['candidate_sha256']
        if mode=='oracle':
            dest=root/'oracles'/task/f'P{roundno}'
            if not dest.exists():run(task,exe,dest,source=new)
        if mode=='functional':
            dest=root/'functional'/task/f'P{roundno}'
            if not dest.exists():probe(task,new,dest)
        if mode=='compare':compare(root,exe,driver,task,roundno,3)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('root','exe','driver'):p.add_argument(k,type=Path)
    p.add_argument('round',type=int);p.add_argument('mode',choices=['oracle','functional','compare'])
    a=p.parse_args();main(a.root.resolve(),a.exe.resolve(),a.driver.resolve(),a.round,a.mode)
