"""Five interleaved native modes, with an independent full Deagle run for both complete models."""
import argparse,collections,hashlib,json,os,resource,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'stage11b'))
import trials
from gates import verify,stock_fallback
from audit import collect,review,save,Refused,CLOCK,read,digest
def rss():
    with open('/proc/self/status') as f:
        return {s.split(':')[0]:int(s.split()[1]) for s in f if s.startswith(('VmRSS:','VmHWM:'))}
def one(args,name,trial,mode):
    original_write=trials.write_plan;measure=trials.measured
    capture={};v,argv=trials.pair_case(name,args.sources,args.fixtures)
    reg=trials.read(trials.ROOT/'reports/evidence/stage-11b/versions/lock-review.json')
    def prepare(d,names,mapping,reason):
        original_write(d,names,mapping,reason)
        if mode not in ('T','C','TC') or d.name!='new':return
        t=CLOCK()
        try:
            if 'stamp' not in capture:raise Refused('old_certificate_unavailable')
            capture['receipt']=review(d.parent/'old',d,capture['stamp'],mode,args.rup)
        except (Refused,subprocess.TimeoutExpired,MemoryError,KeyError,ValueError,OSError) as e:
            (d/'approved.tsv').write_bytes(b'')
            capture['receipt']=(digest(d/'s8-input.bin'),digest(d/'s8-graph.tsv'),hashlib.sha256(b'').hexdigest())
            save(d,'refused.json',dict(path='COLD_DYNAMIC_LEARNING',reason=type(e).__name__+': '+str(e),elapsed_ns=CLOCK()-t))
    def measured(d,*others):
        worker=others[3]
        if d.name=='new' and mode in ('T','C','TC'):
            pipe=worker.stdin
            class ReceiptPipe:
                def write(self,line):
                    seals=' '.join(capture['receipt'])
                    return pipe.write(line+('C11v1 '+seals+'\n').encode())
                def flush(self):pipe.flush()
            worker.stdin=ReceiptPipe()
        before=rss()
        try:res=measure(d,*others)
        finally:
            if d.name=='new' and mode in ('T','C','TC'):worker.stdin=pipe
        if d.name=='old' and mode in ('T','C','TC'):
            t=CLOCK()
            try:capture['stamp']=collect(d,mode)
            except (Refused,MemoryError,KeyError,ValueError,OSError) as e:
                save(d,'refused.json',dict(path='NO_OLD_LIBRARY',reason=str(e),elapsed_ns=CLOCK()-t))
        save(d,'controller-memory.json',dict(before=before,after=rss()))
        return res
    trials.write_plan=prepare;trials.measured=measured
    d=args.out/name/str(trial)/mode
    try:
        trials.run(args,name,trial,mode,v,argv,reg)
        if mode=='stock':return
        t=CLOCK()
        for side in ('old','new'):
            g=verify(d/side,args.out/name/'0/stock'/side)
            if g['native']['path']!='ACCEPT_NATIVE_RESTRICTED':raise Refused('current result gate '+str(g))
            if g['native']['native_exit']==10 and g['strict_request']['strict']!='EXPLICIT_SC_COUNTEREXAMPLE':
                raise Refused('SAT assignment lacks an independent complete SC order')
        doc=read(d/'pair.json');doc['postcheck_ns']=CLOCK()-t
        doc['controller_with_gate_ns']=doc['controller_cycle_ns']+doc['postcheck_ns']
        save(d,'pair.json',doc)
    except Exception as e:
        if mode!='stock' and (args.out/name/'0/stock/pair.json').exists():
            save(d,'fallback.json',stock_fallback(args.out/name/'0/stock',v,argv,e))
        raise
def main():
    p=argparse.ArgumentParser()
    for k in ('exe','worker','rup','sources','fixtures','out'):p.add_argument(k,type=lambda s:Path(s).resolve())
    p.add_argument('--one',nargs=3);p.add_argument('--cases',nargs='+',default=['fib_updates_8','lock12','ticket56-reviewed'])
    p.add_argument('--repeats',type=int,default=5)
    a=p.parse_args();assert trials.file_sha(a.exe)==trials.EXE_SHA
    if a.one:return one(a,a.one[0],int(a.one[1]),a.one[2])
    core=[sys.executable,'-B',str(Path(__file__).resolve()),*map(str,[a.exe,a.worker,a.rup,a.sources,a.fixtures,a.out])]
    for name in a.cases:
        subprocess.run(core+['--one',name,'0','stock'],check=True,timeout=220)
        modes=['F','B','T','C','TC']
        for i in range(a.repeats):
            shifted=modes[i%5:]+modes[:i%5]
            if i%2:shifted.reverse()
            for mode in shifted:
                subprocess.run(core+['--one',name,str(i+1),mode],check=True,timeout=300)
if __name__=='__main__':main()
