"""Secondary properties and a genuine, independently checked long-stack repair attempt."""
from pathlib import Path
import json,shutil,sys
from singles import execute,record
from gates import decide
def check(remote,project):
    d=remote/'panel-extra';d.mkdir(exist_ok=True)
    exe=remote/'native/src/cbmc/deagle_exe'
    vst=project/'reports/evidence/stage-11b/versions'
    for nm in ('stack-old','stack-new'):
        dst=d/nm;dst.mkdir(exist_ok=True);unit=nm+'.i'
        shutil.copyfile(vst/unit,dst/unit)
        row=execute(dst,exe,unit,['--function','main','--deagle-closure','--mm','sc','--32','--unwind','2','--unwinding-assertions'],60)
        record(dst/'receipt.json',row)
    # A push immediately followed by two attempted pops isolates the stale flag.
    scenarios={}
    for repaired in (False,True):
        top=0;flag=False;history=[]
        for op in ('push','consumer','consumer','push','consumer'):
            status='completed'
            if op=='push':top+=1;flag=True
            elif not flag:status='empty: consumer continues'
            elif not top:status='original assertion violation'
            else:
                top-=1
                if repaired:flag=top!=0
            history.append([op,top,flag,status])
        scenarios[str(repaired)]=history
    assert scenarios['False'][2][-1]=='original assertion violation' and scenarios['True'][2][-1].startswith('empty')
    record(d/'stack-functional.json',scenarios)
    for case in ('lock01','lock12','fib_updates_8','batch_retained'):
        for side in ('old','new'):
            base=remote/'formal'/case/'0/stock'/side
            row=json.loads((base/'receipt.json').read_bytes())
            dst=d/(case+'-'+side);dst.mkdir(exist_ok=True)
            for f in row['source']:shutil.copyfile(base/f,dst/f)
            cmd=row['argv'][:];unit=cmd.pop()
            cmd=[k for k in cmd if k not in ('--trace','--json-ui')]
            if '--property' in cmd:
                where=cmd.index('--property');del cmd[where:where+2]
            record(dst/'receipt.json',execute(dst,exe,unit,cmd,60))
    base=json.loads((remote/'formal/lock12/1/GS/new/receipt.json').read_bytes())
    wrong={**base,'exit':10}
    assert decide(wrong,base,{},False)['path']=='FULL_REBUILD'
    assert decide(base,base,{},True)['path']=='FULL_REBUILD'
    record(d/'decision-faults.json',{'altered_verdict':decide(wrong,base,{},False),'missing_strict_certificate':decide(base,base,{},True)})
if __name__=='__main__':check(*[Path(a).resolve() for a in sys.argv[1:]])
