"""Count real native scope method invocations separately from frame disposal, without timing the observer."""
import json
import os
from pathlib import Path
import resource
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def main(observer,work,out):
    plan=json.loads((ROOT/"configs/frozen-pairs.json").read_text())
    results={}
    for case in json.loads((ROOT/"configs/pi1-boundary.json").read_text())["order"]:
        cfg=plan["cases"][case];fixture=work/"fixtures"/case
        protocol="".join(f"APPEND\t{fixture/(side+'.txn')}\nPROBE\t1\n" for side in ("P0","P1"))
        def limits():
            cap=cfg["limits"]["memory_bytes"];resource.setrlimit(resource.RLIMIT_AS,(cap,cap));os.sched_setaffinity(0,{0})
        proc=subprocess.run([observer,"/dev/stdin"],input=protocol,capture_output=True,text=True,preexec_fn=limits,
                            timeout=cfg["limits"]["timeout_seconds"])
        if proc.returncode:raise ValueError(proc.stderr)
        expected=json.loads((work/"raw"/case/"boundary/rows.json").read_text())
        actual=[json.loads(l[4:]) for l in proc.stdout.splitlines() if l.startswith("ROW ")]
        reports=[dict((k,int(v)) for k,v in (f.split("=") for f in l.split()[1:]))
                 for l in proc.stderr.splitlines() if l.startswith("SCOPE ")]
        assert len(reports)==len(actual)==2 and proc.stderr.splitlines()[-1]=="OWNER closure=1 minisat=1 queries=2 same_this=1"
        for e,a,r in zip(expected,actual,reports):
            for k in ("frames","bcp","processed","prefix","empty","theory_props","rebuilds","pushes","pops"):
                assert e["native"][k]==a["native"][k]
            assert r["push_calls"]==a["native"]["pushes"]
            assert r["popped_frames"]+r["destroyed_frames"]==a["native"]["pops"]
        results[case]=dict(native=reports,raw=proc.stderr.splitlines())
    out.write_text(json.dumps(results,indent=2)+"\n")

if __name__=="__main__":main(*(Path(v) for v in sys.argv[1:]))
