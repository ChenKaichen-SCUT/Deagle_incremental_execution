"""Collect final server state after all measured processes have exited."""
import datetime
import json
import sys
import subprocess
from pathlib import Path

def report(raw,output):
    read=lambda p:json.loads(p.read_bytes())
    units=['stage9-formal','stage9-regression','stage9-negative','stage9-details','stage9-acceptance','stage9-release-cli']
    status={u:subprocess.run(['systemctl','is-active',u],text=True,capture_output=True).stdout.strip() for u in units}
    assert all(s=='inactive' for s in status.values()),status
    active=subprocess.check_output(['systemctl','list-units','--state=running','--no-legend','--no-pager','deagle8-*','incdeagle6-*'],text=True).strip()
    assert not active,active
    times=[];shims=set();fronts=set()
    for group,n in [('formal',100),('side',36)]:
        paths=list((raw/group).glob('*/*/*/*/*/complete.json'));assert len(paths)==n
        for p in paths:
            d=p.parent/read(p)['attempt']
            svc=read(d/'service.json')
            assert svc['rc']==0
            times.append((svc['launch'],svc['finish']))
            measure=read(d/'measurement.json')
            for point in measure['processes']:
                if point['kind']=='launch' and point['role']=='frontend':fronts.add(point['pid'])
            for slot in (d/'pair/frontend/compiler-spool').glob('c.*'):shims.add(int(slot.name.split('.')[1]))
    alive_shims=sorted(pid for pid in shims if Path('/proc',str(pid)).exists())
    alive_fronts=sorted(pid for pid in fronts if Path('/proc',str(pid)).exists())
    assert not alive_shims and not alive_fronts,(alive_shims,alive_fronts)
    ordered=sorted(times)
    assert all(b<=c for (_,b),(c,_) in zip(ordered,ordered[1:]))
    out=dict(at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),units=status,active_verification_services=[],
         timed_and_regression_services=len(times),service_seconds=sum(b-a for a,b in times)/1e9,
         first_to_last_seconds=(ordered[-1][1]-ordered[0][0])/1e9,recorded_candidate_dispatcher_pids=len(shims),
         recorded_frontend_pids=len(fronts),candidate_dispatcher_pids_still_present=alive_shims,frontend_pids_still_present=alive_fronts,
         memory_limit_bytes=21474836480,timeout_seconds=300,official_api_calls=0,next_stage_approved=False)
    output.write_bytes((json.dumps(out,indent=2)+'\n').encode())
    print('No live verification services,',len(shims),'recorded dispatchers and',len(fronts),'frontends exited',flush=True)
if __name__=='__main__':report(*[Path(v) for v in sys.argv[1:]])
