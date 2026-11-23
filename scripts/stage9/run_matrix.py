"""Alternate the frozen control and current checkout. One old/candidate service at a time."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
FIRST=('batch_total','threshold_guard','fib_updates_8','split_counter','airline_reservations_6')
OTHER=('partial_counter','batch_retained','fib_updates','airline_reservations')
ORDER=(('before','F1'),('after','F1'),('after','I3'),('before','I3'))


def main(before,source,lock,out,group):
    out.mkdir(parents=True,exist_ok=True)
    todo=[]
    if group=='formal':
        for i in range(5):
            for j,case in enumerate(FIRST[i:]+FIRST[:i]):
                offset=(i+j)%4
                units=ORDER[offset:]+ORDER[:offset]
                if (i+j)%2:units=units[::-1]
                for variant,mode in units:todo.append((variant,case,mode,i+1,False))
    else:
        for case in (*FIRST,*OTHER):
            for variant,mode in ORDER:
                todo.append((variant,case,mode,1,True))
    target=out/('formal' if group=='formal' else 'side')
    target.mkdir(exist_ok=True)
    plan=dict(schedule=todo,baseline='edd7386f8674eb5db08593d327256ea874bf05f6',
              stage7='247894bf77904bb34e547b5a636b8afe8527add4',concurrent_verifications=1,api_calls=0)
    (target/'schedule.json').write_text(json.dumps(plan,indent=2)+'\n')
    for variant,case,mode,i,detail in todo:
        tree=before if variant=='before' else ROOT
        argv=[sys.executable,'-B',str(ROOT/'scripts/stage9/trial.py'),str(tree),str(source),str(lock),
              str(target/variant),case,mode,str(i)]
        if detail:argv.append('--detail')
        subprocess.run(argv,check=True)
    print('Complete',group,len(todo),flush=True)


if __name__=='__main__':
    import fcntl
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('before','source','lock','out'):p.add_argument(n,type=Path)
    p.add_argument('group',choices=('formal','regression'))
    a=p.parse_args()
    with (a.lock.parent/'measurement.lock').open('a') as exclusive:
        fcntl.flock(exclusive,fcntl.LOCK_EX)
        main(a.before.resolve(),a.source.resolve(),a.lock.resolve(),a.out.resolve(),a.group)
