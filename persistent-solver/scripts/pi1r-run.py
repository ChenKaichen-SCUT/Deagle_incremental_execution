"""Run the prespecified serial sessions. Supply the next sealed image only after saving the previous ROW."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys

real=runpy.run_path(str(Path(__file__).with_name("pi1-real.py")))
ROOT=real["ROOT"]; PLAN=json.loads((ROOT/"configs/pi1r-plan.json").read_bytes())
PI1=ROOT/"reports/evidence/pi1"; INDEX=json.loads((PI1/"raw-index.json").read_bytes())


def original(key):
    record=INDEX[key]; data=gzip.decompress((PI1/record["object"]).read_bytes())
    assert hashlib.sha256(data).hexdigest()==record["sha256"]
    return data


def prepare(repo,fixtures,case,side):
    # Called inside the original process exchange, after the last actual result.
    seal=json.loads(original(case+"/solve/seals.json"))[0 if side=="P0" else 1]
    path=fixtures/(side+".txn")
    if not path.is_file():real["frozen"].prepare(repo,fixtures,case,side)
    assert seal["case"]==case and seal["side"]==side
    assert hashlib.sha256(path.read_bytes()).hexdigest()==Path(str(path)+".sha256").read_text().strip()==seal["transaction_sha256"]
    return seal


def run(repo,binary,fixtures,work,phase):
    expected=json.loads((PI1/"runs.json").read_bytes())
    for case,*order in PLAN["ordered_timed_sessions"]:
        for mode in (order if phase!="ledger-off" else ["R2"]):
            out=work/"raw"/phase/case/mode
            if out.exists():raise FileExistsError("Refusing to overwrite "+str(out))
            out.mkdir(parents=True)
            os.environ["PI1R_MODE"]=mode
            for key in ("PI1R_DATABASE","PI1R_LEDGER"):os.environ.pop(key,None)
            if phase=="database":os.environ["PI1R_DATABASE"]=str(out/"reduce")
            if phase=="ledger-off":os.environ["PI1R_LEDGER"]="off"
            print(phase,case,mode,flush=True)
            rows=real["session"](repo,binary,fixtures/case,case,"solve",out,prepare)
            for r,stock in zip(rows,expected[case]["solve"]):
                assert r["properties"]==stock["properties"] and r["status"]==stock["status"]
                assert r["native"]["pushes"]==r["native"]["pops"] and r["native"]["restart_study"]["end_level"]==0
            result={"stage":phase,"mode":mode,"case":case,"cpu":0,"binary_sha256":hashlib.sha256(binary.read_bytes()).hexdigest(),
                    "limits":real["PLAN"]["cases"][case]["limits"],"session_constructions":[r["solver_construct_count"] for r in rows]}
            (out/"run.json").write_text(json.dumps(result,indent=2)+"\n")

if __name__=="__main__":
    a=argparse.ArgumentParser()
    for arg in ("repo","binary","fixtures","work"):a.add_argument(arg,type=Path)
    a.add_argument("phase",choices=["timed","database","ledger-off"]);p=a.parse_args()
    run(p.repo,p.binary,p.fixtures,p.work,p.phase)
