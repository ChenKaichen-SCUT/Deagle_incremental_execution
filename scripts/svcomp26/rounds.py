"""Build the public packet manifest without credentials and run only approved, digest-bound rounds."""
import argparse
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path
from config import ROOT,TASKS,folder
from oracle import metadata,read,save
from packet import packet_for,wire_text

def eligible(root,task,roundno):
    if roundno==1:
        ora=root/('P0-target' if TASKS[task][2]=='primary' else 'P0')/task
        meta=metadata(task)
        if not meta:return
        src=folder(task)/meta['input']
    else:
        prior=root/'rounds'/task/'P1'
        if not (prior/'model.json').is_file() or read(prior/'model.json')['status']!='FROZEN':return
        ora=root/'oracles'/task/'P1';src=prior/'candidate.i'
    if not (ora/'receipt.json').is_file() or read(ora/'receipt.json')['classification']!='VIOLATION':return
    return src,ora
def prepare(root,roundno):
    dest=root/'packets'/f'P{roundno}';dest.mkdir(parents=True,exist_ok=True)
    ids={}
    for task in TASKS:
        pair=eligible(root,task,roundno)
        if not pair:continue
        pkt=packet_for(task,*pair)
        save(dest/(task+'.json'),pkt)
        ids[task]=hashlib.sha256(wire_text(pkt).encode()).hexdigest()
    save(dest/'approved-inputs.json',ids)
    return ids
def live(root,roundno,approved):
    ids=read(approved)
    if not ids:raise ValueError('empty approved manifest')
    key=sys.stdin.readline().strip()
    if not key:raise ValueError('empty credential')
    for task,fingerprint in ids.items():
        src,ora=eligible(root,task,roundno)
        out=root/'rounds'/task/f'P{roundno}';out.parent.mkdir(parents=True,exist_ok=True)
        if out.exists():raise ValueError('attempt already exists')
        prior=list(out.parent.glob('P*/model.json'))
        if len(prior)!=roundno-1:raise ValueError('round budget')
        used=sum(len(read(p)['requests']) for p in prior)
        available=min(2,4-used)
        if available<1:raise ValueError('task request budget exhausted')
        limit=160
        if prior:
            active=sum(read(p.parent/'controller.json')['wall_ns']/1e9 for p in prior)
            limit=min(limit,320-active)
            gen=prior[-1].parent/'generation2/controller.json'
            if gen.exists():limit=min(limit,160-read(gen)['wall_ns']/1e9)
        if limit<=0:raise ValueError('task wall budget exhausted')
        argv=[sys.executable,'-B',str(ROOT/'scripts/svcomp26/repair.py'),task,str(src),str(ora),str(out),'--approved',fingerprint]
        if roundno==2:argv.append('--line-mode')
        if available==1:argv.append('--direct')
        env={k:os.environ[k] for k in ('PATH','HOME','LANG','SSL_CERT_FILE') if k in os.environ}
        env.update(PYTHONDONTWRITEBYTECODE='1',MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT='1',LITELLM_LOCAL_MODEL_COST_MAP='True')
        start=time.monotonic_ns()
        try:
            proc=subprocess.run(argv,input=(key+'\n').encode(),env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=limit)
            rc=proc.returncode
        except subprocess.TimeoutExpired:rc=124
        out.mkdir(exist_ok=True)
        save(out/'controller.json',dict(exit=rc,wall_ns=time.monotonic_ns()-start,hard_timeout_s=limit))
        if not (out/'model.json').exists():
            save(out/'model.json',dict(task=task,status='TIMEOUT_OR_CONTROLLER_FAILURE',requests=[],metering='unavailable',packet_sha256=fingerprint))
        doc=read(out/'model.json');print(task,doc['status'],len(doc['requests']),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','live']);p.add_argument('root',type=Path);p.add_argument('round',type=int,choices=[1,2]);p.add_argument('--approved',type=Path)
    a=p.parse_args()
    if a.mode=='prepare':print(prepare(a.root.resolve(),a.round))
    else:live(a.root.resolve(),a.round,a.approved)
