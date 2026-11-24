"""Check that all measured services, frontend processes and native solver workers have exited."""
import datetime
import json
import subprocess
import sys
from pathlib import Path

def main(raw):
    status={u:subprocess.run(['systemctl','is-active',u],capture_output=True,text=True).stdout.strip()
            for u in ('stage10-build','stage10-pilot','stage10-formal','stage10-final')}
    assert set(status.values())=={'inactive'},status
    pids=set();solvers=set();pairs=[]
    for d in (raw/'final/formal').glob('*/*/*/complete.json'):
        a,b=[json.loads((d.parent/p/'receipt.json').read_bytes()) for p in ('old','candidate')]
        pids.update(r['model_process'] for r in (a,b));solvers.update(r['native'][0]['pid'] for r in (a,b))
        spans=[]
        for p in ('old','candidate'):
            words=[line.split() for line in (d.parent/p/'boundary.tsv').read_text().splitlines()]
            stamps={k:int(v) for k,v in words};spans.append((stamps['factory_begin'],stamps['decider_return']))
        assert spans[0][1]<spans[1][0]
        pairs.append((spans[0][0],spans[1][1]))
    assert len(pairs)==36 and len(pids)==72
    order=sorted(pairs);assert all(a[1]<=b[0] for a,b in zip(order,order[1:]))
    alive=[p for p in pids|solvers if Path('/proc',str(p)).exists()]
    assert not alive,alive
    doc={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'experimental_units':status,
         'formal_model_processes':len(pids),'formal_native_solver_pids':len(solvers),'overlapping_pairs':0,
         'recorded_pids_still_alive':alive,'official_api_calls':0,'stage11_approved':False}
    (raw/'stop.json').write_text(json.dumps(doc,indent=2)+'\n')
if __name__=='__main__':main(Path(sys.argv[1]).resolve())
