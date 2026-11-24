"""Spend a second generation round on an independently rechecked P0 when round one supplied no version."""
import os
import shutil
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path
from config import ROOT,folder
from oracle import metadata,read,save,sha
from packet import packet_for,wire_text
from incdeagle.repair_input import packet_sha
TASKS=('read_write_lock-2','unwind1-1')
def packets(root):
    d={}
    for task in TASKS:
        src=folder(task)/metadata(task)['input'];ora=root/'preflight/recheck'/task
        obj=packet_for(task,src,ora);d[task]=packet_sha(obj)
    return d
def live(root,approved):
    ids=packets(root);assert ids==read(approved)
    secret=sys.stdin.readline().strip();assert secret
    for task in TASKS:
        src=folder(task)/metadata(task)['input'];ora=root/'preflight/recheck'/task
        parent=root/'rounds'/task/'P1'
        original=read(parent/'model.json');control=read(parent/'controller.json')
        assert original['status']=='FAILED' and len(original['requests'])==2 and not (parent/'candidate.i').exists()
        assert Decimal(original['estimated_usd']['peak'])+Decimal('.07')<=Decimal('.14')
        first=parent/'generation1';first.mkdir()
        for f in ('model.json','controller.json'):shutil.copyfile(parent/f,first/f)
        new=parent/'generation2';cmd=[sys.executable,'-B',str(ROOT/'scripts/svcomp26/repair.py'),task,str(src),str(ora),str(new),'--approved',ids[task],'--line-mode']
        start=time.monotonic_ns();env={k:os.environ[k] for k in ('HOME','PATH','LANG','SSL_CERT_FILE') if k in os.environ}
        try:rc=subprocess.run(cmd,input=(secret+'\n').encode(),env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=160).returncode
        except subprocess.TimeoutExpired:rc=124
        elapsed=time.monotonic_ns()-start;new.mkdir(exist_ok=True)
        save(new/'controller.json',dict(exit=rc,wall_ns=elapsed,hard_timeout_s=160))
        result=read(new/'model.json') if (new/'model.json').exists() else dict(task=task,status='TIMEOUT_OR_CONTROLLER_FAILURE',requests=[],estimated_usd={'peak':None,'off_peak':None},metering='unavailable')
        assert len(result['requests'])<=2
        for f in ('repair.patch','candidate.i'):
            if (new/f).exists():shutil.copyfile(new/f,parent/f)
        result['requests']=original['requests']+result['requests']
        result['generations']=2;result['generation_1_outcome']=original['status'];result['generation_2_parent']='P0 independently rechecked'
        result['elapsed_ns']=original['elapsed_ns']+result.get('elapsed_ns',elapsed)
        result['estimated_usd']={k:str(Decimal(original['estimated_usd'][k])+Decimal(v)) if v is not None else None for k,v in result['estimated_usd'].items()}
        save(parent/'model.json',result);save(parent/'controller.json',dict(exit=rc,wall_ns=control['wall_ns']+elapsed,hard_timeout_s=320,generations=2))
        print(task,result['status'],len(result['requests']),flush=True)
if __name__=='__main__':
    mode,raw,approved=sys.argv[1:];root=Path(raw).resolve();dest=Path(approved)
    if mode=='prepare':save(dest,packets(root))
    elif mode=='live':live(root,dest)
    else:raise ValueError(mode)
