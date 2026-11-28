"""Serial frozen controls. The child receives its next transaction only after its previous ROW is saved."""
import argparse
import csv
import gzip
import importlib.util
import io
import json
import os
import resource
import signal
import statistics
import struct
import subprocess
import time
from pathlib import Path
from frozen import STOCK, blob, digest, require, save

ROOT=Path(__file__).resolve().parents[1]
PLAN=json.loads((ROOT/"configs/frozen-pairs.json").read_bytes())
REG=json.loads((ROOT/"configs/pi1-boundary.json").read_bytes())
spec=importlib.util.spec_from_file_location("pi_frozen",Path(__file__).with_name("pi1-frozen.py"))
frozen=importlib.util.module_from_spec(spec);spec.loader.exec_module(frozen)


def limits(spec):
    os.sched_setaffinity(0,{0})
    cap=spec["limits"]["memory_bytes"]
    resource.setrlimit(resource.RLIMIT_AS,(cap,cap))


def baseline(repo):
    ref=blob(repo,"reports/evidence/d43e/runs.tsv")
    d={c:[] for c in REG["order"]}
    for r in csv.DictReader(io.StringIO(ref.decode()),delimiter="\t"):
        if r["mode"]=="stock" and r["side"]=="P1":d[r["case"]].append(int(r["wall_ns"])*1e-9)
    return {k:statistics.median(v) for k,v in d.items()}


def pack(path):
    path.with_suffix(path.suffix+".gz").write_bytes(gzip.compress(path.read_bytes(),compresslevel=6,mtime=0))


def stock_run(repo,stock,case,side,out):
    d=out/("stock-"+side);d.mkdir(parents=True,exist_ok=True)
    cfg=PLAN["cases"][case];placed={}
    for name,rel in cfg["staged"][side].items():
        data=blob(repo,f"bench/{case}/{rel}");require(digest(data)==cfg["files_sha256"][rel],"stock source lock")
        (d/name).write_bytes(data);placed[name]=digest(data)
    require(digest(stock.read_bytes())==STOCK,"wrong stock ELF")
    start=time.monotonic()
    with (d/"stdout").open("wb") as stdout,(d/"stderr").open("wb") as stderr:
        proc=subprocess.Popen([stock,*cfg["argv"]],stdout=stdout,stderr=stderr,cwd=d,preexec_fn=lambda:limits(cfg),start_new_session=True)
        try:rc=proc.wait(timeout=cfg["limits"]["timeout_seconds"])
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGKILL);proc.wait();raise
    elapsed=time.monotonic()-start
    text=(d/"stdout").read_text()
    # Stock emits native solver messages on stdout interleaved with JSON. Use the existing stock extractor.
    import re
    clean="\n".join(line for line in text.splitlines() if not re.match(r"^(ClosureSolver finishes|Attempts to add co clauses|Solving|see the equation|finish seeing|WARNING:|ERROR:)",line))
    # Extract result objects directly, preserving each complete property's status, trace and source location.
    decoder=json.JSONDecoder();results=None
    for i in (m.end() for m in re.finditer(r'"result"\s*:\s*',clean)):
        try:
            val=decoder.raw_decode(clean,i)[0]
            if isinstance(val,list) and all("property" in r for r in val):results=val
        except (ValueError,TypeError):pass
    require(results is not None and rc in (0,10),"stock complete property result missing")
    meta=dict(wall=elapsed,returncode=rc,properties={r["property"]:r["status"] for r in results},
              argv=cfg["argv"],limits=cfg["limits"],cpu=0,binary=STOCK,inputs=placed,
              stdout=digest((d/"stdout").read_bytes()),stderr=digest((d/"stderr").read_bytes()))
    save(d/"receipt.json",meta);pack(d/"stdout");pack(d/"stderr")
    return meta


def session(repo,binary,fixtures,case,mode,out):
    cfg=PLAN["cases"][case];out.mkdir(parents=True,exist_ok=True)
    controls=out/"assumptions.i32le";env=dict(os.environ,PI1_ASSUMPTION_FILE=str(controls))
    transcript=out/"native.txt"; rows=[];seals=[]
    def timeout(*_):raise TimeoutError("frozen per-version deadline")
    old=signal.signal(signal.SIGALRM,timeout)
    with transcript.open("w") as log,(out/"stderr").open("w") as err:
        child=subprocess.Popen([binary,"/dev/stdin"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,
            text=True,env=env,start_new_session=True,preexec_fn=lambda:limits(cfg))
        try:
            for side in ("P0","P1"):
                seal=frozen.prepare(repo,fixtures,case,side);seals.append(seal)
                begin=time.monotonic()
                signal.setitimer(signal.ITIMER_REAL,cfg["limits"]["timeout_seconds"])
                child.stdin.write("APPEND\t"+str(fixtures/(side+".txn"))+"\n"+("PROBE" if mode=="boundary" else "SOLVE")+"\t1\n")
                child.stdin.flush()
                for line in child.stdout:
                    log.write(line)
                    if line.startswith("ROW "):
                        row=json.loads(line[4:]);row["elapsed_backend_transaction_s"]=time.monotonic()-begin
                        row["side"]=side;row["native_vars"]=seal["native_vars"];rows.append(row);log.flush()
                        save(out/"rows.json",rows);break
                else:raise RuntimeError("backend exited: "+(out/"stderr").read_text()[-350:])
                signal.setitimer(signal.ITIMER_REAL,0)
                require(row["solver_construct_count"]==1 and row["old_learnt_export_count"]==row["old_learnt_import_count"]==row["per_clause_reproof_count"]==0,"isolation")
                print(case,mode,side,row["status"],row["native"]["boundary_status"],round(row["native"]["boundary"],3),row["native"]["prefix"],flush=True)
            child.stdin.close();rc=child.wait(timeout=10);require(rc==0,"backend failed at close")
        finally:
            signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old)
            if child.poll() is None:os.killpg(child.pid,signal.SIGKILL);child.wait()
    save(out/"seals.json",seals)
    data=controls.read_bytes();start=0
    for idx,row in enumerate(rows):
        version,query,n,ncontrol=struct.unpack_from("<4I",data,start);start+=16
        words=memoryview(data)[start:start+4*n].cast("I"); start+=4*n
        m=row["native"]
        require(version==idx+1 and query==1 and n==m["assumptions"] and sum(w&1 for w in words)==m["negative"],"assumptions receipt mismatch")
        require(len({w//2 for w in words[:ncontrol]})==ncontrol,"duplicate signed selector")
        if mode=="boundary":require(row["status"]=="DIAGNOSTIC" and m["decisions"]==0 and m["pushes"]==m["pops"],"invalid probe")
    require(start==len(data),"trailing assumptions")
    pack(controls);pack(transcript)
    return rows


def main():
    ap=argparse.ArgumentParser()
    for a in ("repo","binary","stock","work"):ap.add_argument(a,type=Path)
    ap.add_argument("mode",choices=("boundary","solve"));ap.add_argument("case",choices=REG["order"])
    a=ap.parse_args();case=a.case;dest=a.work/"raw"/case;dest.mkdir(parents=True,exist_ok=True)
    refs=baseline(a.repo);cfg=PLAN["cases"][case]
    if a.mode=="boundary":
        existing=dest/"stock-P1"/"receipt.json"
        ctrl=json.loads(existing.read_text()) if existing.exists() else stock_run(a.repo,a.stock,case,"P1",dest)
        require(ctrl["binary"]==STOCK and ctrl["cpu"]==0 and ctrl["argv"]==cfg["argv"],"stock control receipt")
    else:
        for c in REG["order"]:
            gate=json.loads((a.work/"raw"/c/"warning.json").read_text())
            require(not gate["stop"],"assumption stop gate")
        existing=dest/"stock-P0"/"receipt.json"
        ctrl=json.loads(existing.read_text()) if existing.exists() else stock_run(a.repo,a.stock,case,"P0",dest)
        require(ctrl["binary"]==STOCK and ctrl["cpu"]==0 and ctrl["argv"]==cfg["argv"],"stock P0 receipt")
    rows=session(a.repo,a.binary,a.work/"fixtures"/case,case,a.mode,dest/a.mode)
    if a.mode=="boundary":
        r=rows[-1]["native"];ratio=r["boundary"]/refs[case]
        gate=dict(case=case,stock_reference_s=refs[case],contemporary_stock_P1_s=ctrl["wall"],boundary_s=r["boundary"],
                  ratio=ratio,stop=ratio>=0.5 or any(x["native"]["rebuilds"]>1 for x in rows),
                  completed_prefix=r["prefix"],total=r["assumptions"],diagnostic=r["boundary_status"])
        save(dest/"warning.json",gate);print(gate,flush=True)
    else:
        for row in rows:
            ref=json.loads((dest/("stock-"+row["side"])/"receipt.json").read_text())
            target=cfg["target"];require(row["properties"].get(target)==ref["properties"].get(target),"native target differs")
            require(row["status"]==("SAT" if ref["properties"][target]=="FAILURE" else "UNSAT"),"target query differs")

if __name__=="__main__":main()
