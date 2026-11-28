"""Collect lossless native/stock data, check both versions and reproduce the PI-1 tables offline."""
import argparse
import collections
import gzip
import hashlib
import importlib
import io
import json
import os
import platform
import struct
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from frozen import STOCK, blob, digest, require, save

ROOT=Path(__file__).resolve().parents[1]
REG=json.loads((ROOT/"configs/pi1-boundary.json").read_text())
PLAN=json.loads((ROOT/"configs/frozen-pairs.json").read_text())


def read(path):return json.loads(path.read_bytes())


def small_bundle(src,dest):
    with dest.open("wb") as raw,gzip.GzipFile(fileobj=raw,mode="wb",mtime=0) as z,tarfile.open(fileobj=z,mode="w|") as tar:
        for path in sorted(src.rglob("*")):
            if not path.is_file():continue
            data=path.read_bytes()
            item=tarfile.TarInfo(path.relative_to(src).as_posix());item.size=len(data);item.mode=0o644
            tar.addfile(item,io.BytesIO(data))


def normalize(p):
    d=dict(p)
    if "sourceLocation" in d:d["sourceLocation"]={k:v for k,v in d["sourceLocation"].items() if k!="workingDirectory"}
    return d


def archive(args):
    repo,work,dev,dest=args.repo,args.work,args.dev,args.evidence
    dest.mkdir(parents=True,exist_ok=True);objects=dest/"objects";objects.mkdir(exist_ok=True)
    assets={};cohort={};props={}
    def remember(path,kind):
        raw=path.read_bytes();h=digest(raw);target=objects/(h+".gz")
        if not target.exists():target.write_bytes(gzip.compress(raw,compresslevel=6,mtime=0))
        assets[kind]=dict(object=target.relative_to(dest).as_posix(),sha256=h,bytes=len(raw))
    c43=json.loads(blob(repo,"reports/evidence/d43e/native-properties.json"))
    with tempfile.TemporaryDirectory() as td:
        for m in ("lock_build","run_stock","summarize_stock"):
            (Path(td)/(m+".py")).write_bytes(blob(repo,"scripts/"+m+".py"))
        sys.path.insert(0,td);interpret=importlib.import_module("summarize_stock").interpret
        for case in REG["order"]:
            folder=work/"raw"/case;cfg=PLAN["cases"][case];data={"gate":read(folder/"warning.json")};pc={}
            for mode in ("boundary","solve"):
                f=folder/mode
                for name in ("native.txt","assumptions.i32le","stderr","rows.json","seals.json"):
                    remember(f/name,"/".join([case,mode,name]))
                rows=read(f/"rows.json")
                data[mode]=[{k:v for k,v in r.items() if k not in ("order","assignment")} for r in rows]
                if mode=="solve" and rows[0]["status"]=="SAT":data["P0_witness"]=read(f/"witness.json")
            for i,side in enumerate(("P0","P1")):
                d=folder/("stock-"+side);meta=read(d/"receipt.json")
                for name in ("stdout","stderr","receipt.json"):remember(d/name,"/".join([case,"stock-"+side,name]))
                parsed,failures=interpret(dict(exit_code=meta["returncode"],argv=meta["argv"],target=cfg["target"]),
                                          (d/"stdout").read_text())
                ref=c43[case]["1"]["stock-clock/"+side]["properties"]
                attr=("classification","unwinding_iterations","unwinding_stop_or_warning","enabled_unwinding_assertions",
                      "unwinding_property_ids","adapter_query_count","target_status","cProverStatus")
                require(all(ref[k]==parsed[k] for k in attr),"stock/unwinding drift "+case+" "+side)
                require(list(map(normalize,ref["properties"]))==list(map(normalize,parsed["properties"])),"property catalogue drift")
                row=data["solve"][i]
                require(row["properties"]==meta["properties"] and set(row["properties"])==set(read(work/"fixtures"/case/(side+"-seal.json"))["properties"]),
                        "persistent query deviates from unmodified stock")
                pc[side]={k:parsed[k] for k in attr}
                pc[side].update(properties=list(map(normalize,parsed["properties"])),persistent=row["properties"],
                                stock_witness_steps=parsed["trace_step_counts"],stock_wall_s=meta["wall"])
            cohort[case]=data;props[case]=pc
    save(dest/"runs.json",cohort);save(dest/"properties.json",props)
    small_bundle(args.small,dest/"native-small.tar.gz")
    for name in ("staging-failure.log","nonunit-failure.log","debug-site.txt","fib-snapshot-11-solve.log"):
        p=dev/"raw"/name
        if p.exists():remember(p,"development/"+name)
    for case in REG["order"]:
        f=dev/"raw"/case/"solve"
        for name in ("rows.json","native.txt","stderr"):
            if (f/name).exists():remember(f/name,"development/"+case+"/"+name)
    save(dest/"raw-index.json",assets)
    save(dest/"build.json",dict(source_commit=args.source,baseline=REG["baseline"],stock=STOCK,
        executable_sha256=digest(args.binary.read_bytes()),stock_control_sha256=digest(args.stock_control.read_bytes()),
        compiler=subprocess.check_output(["g++","--version"],text=True).splitlines()[0],
        os=platform.platform(),cpu=[0],native_source="minisat-2.2.1/minisat/core",
        build_command="bash persistent-solver/scripts/build-pi1.sh OUT",
        build_log=(dev/"raw/final-compile.log").read_text(),caps={k:v["limits"] for k,v in PLAN["cases"].items()},
        core_objects={f.name:digest(f.read_bytes()) for f in sorted(args.binary.parent.glob("*.o"))}))
    return verify(dest)


def verify(dest):
    assets=read(dest/"raw-index.json");runs=read(dest/"runs.json");props=read(dest/"properties.json")
    def load(key):
        a=assets[key];data=gzip.decompress((dest/a["object"]).read_bytes())
        require(len(data)==a["bytes"] and digest(data)==a["sha256"],"corrupt raw "+key);return data
    for k in assets:load(k)
    core={}
    with tarfile.open(dest/"native-small.tar.gz","r:gz") as tar:
        require(tar.extractfile("owner.txt").read().strip()==b"OWNER closure=1 minisat=1 queries=2 same_this=1","native construction count")
        for name in ("small/small.json","exhaustive/checks.json","boundaries/checks.json"):
            core[name]=json.load(tar.extractfile(name))
    finite=core["small/small.json"]
    for n,entry in finite.items():require(entry["statuses"]==entry["independent_stock"],"small stock "+n)
    require(finite["native_learning"]["metrics"][1]["families"][0]["hits"][0]>0,"missing old native use")
    require(finite["dynamic_co"]["co_clauses"]==1,"dynamic CO")
    for name,entry in core["exhaustive/checks.json"].items():
        require(entry["actual"]==entry["expected"]==entry["stock"],"order enumeration "+name)
    cases={}
    for case in REG["order"]:
        data=runs[case];cfg=PLAN["cases"][case];sid={}
        for mode in ("boundary","solve"):
            base=case+"/"+mode+"/";signed=load(base+"assumptions.i32le")
            raw=[json.loads(l[4:]) for l in load(base+"native.txt").splitlines() if l.startswith(b"ROW ")]
            external=json.loads(load(base+"rows.json"));p=0;require(len(raw)==len(external)==2,"version count")
            for i,(r,record) in enumerate(zip(raw,data[mode])):
                side=("P0","P1")[i];m=r["native"];hdr=struct.unpack_from("<4I",signed,p);p+=16
                n=hdr[2];codes=memoryview(signed)[p:p+4*n].cast("I");p+=4*n
                require(hdr[:2]==(i+1,1) and n==m["assumptions"]==m["negative"]+m["positive"]
                        and sum(x&1 for x in codes)==m["negative"],"assumption words")
                require(hdr[3]==r["selectors"] and len({c//2 for c in codes[:hdr[3]]})==hdr[3],"active and inactive controls")
                require(record["native"]==external[i]["native"]==m and record["rss_kib"]==r["rss_kib"],"metric mismatch")
                require(r["solver_construct_count"]==1 and r["old_learnt_export_count"]==r["old_learnt_import_count"]==r["per_clause_reproof_count"]==0,
                        "persistent session isolation")
                require(m["pushes"]==m["pops"] and r["rss_kib"]*1024<cfg["limits"]["memory_bytes"],"resource/scope")
                if mode=="boundary":
                    require(r["status"]=="DIAGNOSTIC" and m["decisions"]==0 and m["prefix"]<=n,"boundary diagnosis")
                else:
                    require(m["solver_instance"]==raw[0]["native"]["solver_instance"],"solver identity changed")
                    require(r["properties"]==props[case][side]["persistent"],"property mismatch")
                    if r["status"]=="SAT":require(len(r["assignment"])==record["native_vars"] and r["order"],"missing owned model")
            require(p==len(signed),"trailing signed control words")
        for a,b in zip(data["solve"][0]["native"]["families"],data["solve"][1]["native"]["families"]):
            require(b["physical"]==a["resident_end"] and b["physical"]==b["constraining"]+b["dormant"],"lost resident population")
            require(b["distinct_used"]-b["dormant_distinct_used"]<=b["constraining"],"effective use")
        cases[case]=dict(statuses=[r["status"] for r in data["solve"]],
                         effective_old_hits=sum(f["distinct_used"]-f["dormant_distinct_used"] for f in data["solve"][1]["native"]["families"]),
                         boundary_ratio=data["gate"]["ratio"])
    result=dict(stage="PI-1",observed_native_constructors={"ClosureSolver":1,"Solver":1,"queries_on_same_object":2},small_sequences=len(finite),finite_versions=sum(len(v["statuses"]) for v in finite.values()),
        forced_port_valuations=sum(len(v["actual"]) for v in core["exhaustive/checks.json"].values()),
        transaction_rejections=core["boundaries/checks.json"]["rejections"],allocator_faults=core["boundaries/checks.json"]["allocator_faults_rejected"],
        late_conflict_normalizations=core["boundaries/checks.json"]["delayed"]["cycle"]["delayed_conflicts"],
        raw_entries=len(assets),unique_raw_objects=len({v["object"] for v in assets.values()}),cases=cases)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result


def main():
    ap=argparse.ArgumentParser();sp=ap.add_subparsers(dest="command",required=True)
    cmd=sp.add_parser("collect")
    for k in ("repo","work","dev","small","binary","stock_control","evidence"):cmd.add_argument(k,type=Path)
    cmd.add_argument("source")
    cmd=sp.add_parser("verify");cmd.add_argument("evidence",type=Path)
    a=ap.parse_args()
    if a.command=="collect":save(a.evidence/"checks.json",archive(a))
    else:
        result=verify(a.evidence);require(result==read(a.evidence/"checks.json"),"independent summary drift")
if __name__=="__main__":main()
