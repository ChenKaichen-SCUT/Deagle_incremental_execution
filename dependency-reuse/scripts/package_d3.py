"""Validate every completed run and archive reconstructible frozen D3 results."""
import argparse
import gzip
import hashlib
import json
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

from diff_d1 import digest
from package_d1 import packed
from prepare_d2 import prepare
from prepare_d3 import facts
from recheck_d2 import logical_sha
from run_d1 import CASES
from run_stock import BASE,save
from verify_d3_boundary import verify


def read(path):
    return json.loads(path.read_text())


def counts(path):
    return {k:int(n) for k,n in (r.split() for r in path.read_text().splitlines())}


def same_graph(left,right):
    # Bind the frozen D1 local node IDs, directed APO pairs, RF/guard bindings,
    # B/Q stream and configuration to this recorder's actual joint invocation.
    tags={b"NODE",b"MEMBER",b"IN",b"OUT",b"EDGE",b"GUARD",b"C",b"K",b"N",b"TARGET",b"QUERY"}
    def selected(f):
        for line in f:
            if line.partition(b"\t")[0] in tags:yield line
    with gzip.open(left,"rb") as a,right.open("rb") as b:
        from itertools import zip_longest
        if any(x!=y for x,y in zip_longest(selected(a),selected(b))):raise ValueError("D1 local graph/Boolean binding changed")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("runs","observer","mapping","engine","checker","new_checks","new_evidence"):
        p.add_argument(name,type=Path)
    a=p.parse_args()
    checks,ev=a.new_checks.resolve(),a.new_evidence.resolve()
    checks.mkdir(parents=True,exist_ok=False)
    ev.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(a.runs/"plan.json",ev/"plan.json")
    mapping=ev/"mapping"
    mapping.mkdir()
    for name in ("plan.json","native-cost.json","summary.json"):
        shutil.copyfile(a.mapping/name,mapping/name)
    summaries={}
    for case in CASES:
        tmp=checks/case
        tmp.mkdir()
        pair=ev/"pairs"/case
        pair.mkdir(parents=True)
        joint=a.runs/case/"joint-1/native.tsv"
        peer=a.mapping/"manifests"/case/"P1/after/native.tsv"
        p0,p1=pair/"P0-native.tsv.gz",pair/"P1-native.tsv.gz"
        packed(joint,p0)
        packed(peer,p1)
        frozen=BASE/"reports/evidence/d1"
        same_graph(frozen/"runs/record"/case/"P0/native.tsv.gz",joint)
        current=pair/"delta"
        subprocess.run([sys.executable,BASE/"scripts/diff_d1.py",joint,peer,a.engine,current,"--d3-mapping"],check=True)
        for improvement in (False,True):
            change=current if improvement else frozen/"pairs"/case
            source=p0 if improvement else frozen/"runs/record"/case/"P0/native.tsv.gz"
            dest=tmp/("improved" if improvement else "frozen")
            prepare(case,dest,pair=change,native=source)
            facts(source,change,dest/"declarations.txt")
        native=a.observer/case/"work"
        for name in ("native-learns.tsv","native-theory.tsv"):
            packed(native/name,pair/(name+".gz"))
        if digest(native/"native-learns.tsv")!=hashlib.sha256(gzip.open(BASE/"reports/evidence/d2/pairs"/case/"native-learns.tsv.gz","rb").read()).hexdigest():
            raise ValueError("independent D1 observations differ from reviewed D2")
        resources=[];variants={}; primary=None
        for c,rep,mode in read(ev/"plan.json")["schedule"]:
            if c!=case:continue
            name=f"{mode}-{rep}"
            src=a.runs/case/name;out=pair/name
            out.mkdir()
            for f in ("stdout","stderr"):packed(src/f,out/(f+".gz"))
            for f in ("run.json","result.json","trace.json"):shutil.copyfile(src/f,out/f)
            meta=read(src/"run.json");res=read(src/"result.json")
            r=dict(mode=mode,repeat=rep,wall_s=meta["wall_ns"]/1e9,rss_kib=meta["peak_rss_kib"],
                   solver_s=res["queries"][0]["property_decider_solve_s"],exit_code=meta["exit_code"])
            resources.append(r)
            if mode=="off":continue
            proof=src/"proof.bin"
            logical,clocks=logical_sha(proof)
            if logical not in variants:
                fname=f"proof-{name}.bin.gz"
                packed(proof,pair/fname)
                variants[logical]=fname
            r.update(raw_bytes=proof.stat().st_size,raw_sha256=digest(proof),logical_sha256=logical,
                     compressed_payload=variants[logical],footer_clocks=clocks)
            if mode=="boolean":continue
            r["checked_native_boundaries"]=verify(proof,native/"native-theory.tsv")
            for scope in ("improved","frozen"):
                # Each D3 run receives full replay under both original and improved mapping.
                inputs=tmp/scope
                audit=tmp/name/scope
                audit.mkdir(parents=True)
                subprocess.run([a.checker,proof,inputs/"inputs.txt",inputs/"mapped.txt",native/"native-learns.tsv",
                                inputs/"declarations.txt",audit],check=True)
                m=counts(audit/"metrics.tsv")
                r[scope]=m
                shutil.copyfile(audit/"metrics.tsv",out/(scope+"-metrics.tsv"))
                hashes={f:digest(audit/f) for f in ("learned.tsv","used.tsv","survivors.tsv","mixed-witness.tsv") if (audit/f).exists()}
                r[scope+"_hashes"]=hashes
                if primary is None:
                    for f in hashes:packed(audit/f,pair/(scope+"-"+f+".gz"))
                elif hashes!=primary[scope+"_hashes"]:
                    for f in hashes:packed(audit/f,out/(scope+"-"+f+".gz"))
            if primary is None:primary=r
        save(pair/"runs.json",resources)
        median={mode:{metric:statistics.median(z[metric] for z in resources if z["mode"]==mode)
                     for metric in ("wall_s","solver_s","rss_kib")} for mode in ("off","boolean","mixed","joint")}
        summaries[case]=dict(medians=median,improved=primary["improved"],frozen=primary["frozen"],
                             boundary=primary["checked_native_boundaries"],raw_bytes=primary["raw_bytes"])
    save(ev/"summary.json",summaries)


if __name__=="__main__":main()
