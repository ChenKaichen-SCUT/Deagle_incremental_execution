"""Execute the registered serial arms and the pristine same-transaction cold reference."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import time

scale=runpy.run_path(str(Path(__file__).with_name("pi1g-scale.py")))
prev=scale["previous"];real=prev["real"];plan=scale["PLAN"]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def run(repo,binary,fixtures,work,phase,stock):
    for case,*modes in plan["ordered_sessions"]:
        cfg=real["PLAN"]["cases"][case]
        if phase=="native-cold":
            assert sha(stock)==json.loads((prev["PI1"]/"build.json").read_bytes())["stock_control_sha256"]
            for side in ("P0","P1"):
                seal=prev["prepare"](repo,fixtures/case,case,side)
                out=work/"raw"/phase/case/side;out.mkdir(parents=True)
                t=time.monotonic()
                with (out/"stdout").open("w") as f,(out/"stderr").open("w") as err:
                    p=subprocess.run(["/usr/bin/time","-f","%M","-o",out/"rss",stock,fixtures/case/(side+".txn")],
                        stdout=f,stderr=err,timeout=cfg["limits"]["timeout_seconds"],preexec_fn=lambda:real["limits"](cfg))
                wall=time.monotonic()-t
                raw=(out/"stdout").read_text()
                match=re.findall(r"^STOCK (SAT|UNSAT|UNKNOWN)$",raw,re.M)
                assert p.returncode==0 and match==[json.loads(prev["original"](case+"/solve/rows.json"))[int(side=="P1")]["status"]],(case,side,match)
                v=dict(status=match[0],backend_wall_s=wall,rss_kib=int((out/"rss").read_text()),binary=sha(stock),
                       model=seal["transaction_sha256"],limits=cfg["limits"],cpu=0)
                (out/"receipt.json").write_text(json.dumps(v,indent=2)+"\n")
                print(phase,case,side,round(wall,3),flush=True)
            continue
        for mode in modes:
            d=work/"raw"/phase/case/mode;d.mkdir(parents=True)
            os.environ.update(PI1G_MODE=mode,PI1R_MODE="R2")
            for key in ("PI1R_DATABASE","PI1G_INVENTORY","PI1G_AUDIT","PI1R_LEDGER"):os.environ.pop(key,None)
            if phase=="timed":os.environ["PI1R_LEDGER"]="off"
            else:os.environ.update(PI1G_INVENTORY=str(d/"inventory.jsonl"),PI1G_AUDIT=str(d/"activation.bin"))
            print(phase,case,mode,flush=True)
            rows=real["session"](repo,binary,fixtures/case,case,"solve",d,prev["prepare"],
                                (1,2) if mode=="Grouped-Reset-active" else (1,1))
            for r,ref in zip(rows,json.loads(prev["original"](case+"/solve/rows.json"))):
                assert (r["properties"],r["status"])==(ref["properties"],ref["status"]),(case,mode,r["side"])
                n=r["native"];s=n["restart_study"];assert s["mode"]=="R2" and s["ledger"]==(phase=="audit")
                assert n["pushes"]==n["pops"] and s["end_graph"]==s["end_level"]==0
            (d/"run.json").write_text(json.dumps(dict(mode=mode,phase=phase,case=case,cpu=0,
                    binary=sha(binary),limits=cfg["limits"]),indent=2)+"\n")

if __name__=="__main__":
    a=argparse.ArgumentParser()
    for x in ("repo","binary","fixtures","work","stock"):a.add_argument(x,type=Path)
    a.add_argument("phase",choices=["timed","audit","native-cold"]);v=a.parse_args()
    run(v.repo,v.binary,v.fixtures,v.work,v.phase,v.stock)
