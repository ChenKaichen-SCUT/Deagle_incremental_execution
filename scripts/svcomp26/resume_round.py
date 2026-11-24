"""Use the single remaining first-round request only for two length-truncated public tasks."""
import os
import shutil
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path
from rounds import eligible
from config import ROOT
from oracle import read,save
from incdeagle.repair_input import packet_sha
from packet import packet_for

def main(root,approved):
    key=sys.stdin.readline().strip();assert key
    ids=read(approved)
    for task in ('read_write_lock-2','unwind1-1'):
        parent=root/'rounds'/task/'P1';src,ora=eligible(root,task,1);initial=read(parent/'model.json');ctr=read(parent/'controller.json')
        assert initial['status']=='FAILED' and len(initial['requests'])==1 and initial['requests'][0]['finish_reason']=='length'
        assert initial['packet_sha256']==ids[task]==packet_sha(packet_for(task,src,ora))
        limit=160-ctr['wall_ns']/1e9
        assert limit>5
        first=parent/'attempt1';first.mkdir()
        for f in ('model.json','controller.json'):shutil.copyfile(parent/f,first/f)
        retry=parent/'attempt2'
        argv=[sys.executable,'-B',str(ROOT/'scripts/svcomp26/repair.py'),task,str(src),str(ora),str(retry),'--approved',ids[task],'--direct']
        env={k:os.environ[k] for k in ('PATH','HOME','LANG','SSL_CERT_FILE') if k in os.environ}
        tick=time.monotonic_ns()
        try:rc=subprocess.run(argv,input=(key+'\n').encode(),env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=limit).returncode
        except subprocess.TimeoutExpired:rc=124
        retry.mkdir(exist_ok=True);elapsed=time.monotonic_ns()-tick
        save(retry/'controller.json',dict(exit=rc,wall_ns=elapsed,hard_timeout_s=limit))
        if not (retry/'model.json').exists():
            save(retry/'model.json',dict(task=task,status='TIMEOUT_OR_CONTROLLER_FAILURE',requests=[],metering='unavailable',estimated_usd={'peak':None,'off_peak':None}))
        result=read(retry/'model.json')
        assert len(result['requests'])<=1
        for f in ('candidate.i','repair.patch'):
            if (retry/f).exists():shutil.copyfile(retry/f,parent/f)
        result['attempts']=['attempt1','attempt2'];result['requests']=initial['requests']+result['requests']
        result['elapsed_ns']=initial['elapsed_ns']+result.get('elapsed_ns',elapsed)
        result['estimated_usd']={k:str(Decimal(initial['estimated_usd'][k])+Decimal(v)) if v is not None else None for k,v in result['estimated_usd'].items()}
        assert result['estimated_usd']['peak'] is None or Decimal(result['estimated_usd']['peak'])<=Decimal('.14')
        save(parent/'model.json',result);save(parent/'controller.json',dict(exit=rc,wall_ns=ctr['wall_ns']+elapsed,hard_timeout_s=160,attempts=2))
        print(task,result['status'],len(result['requests']),flush=True)
if __name__=='__main__':main(Path(sys.argv[1]).resolve(),Path(sys.argv[2]))
