"""Check all preregistered runs and archive exact, reconstructible proof stores."""
import argparse
import gzip
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import tarfile

from diff_d1 import digest
from inspect_d2_used import inspect
from package_d1 import metrics as search_signature, packed, trace_comparison
from prepare_d2 import occurrences
from recheck_d2 import logical_sha
from run_d1 import CASES
from run_stock import BASE,save
from summarize_stock import interpret


def table(path):
    return {k:int(n) for k,n in (line.split() for line in path.open())}


def compact_self(pair,dest):
    dest.mkdir(parents=True)
    shutil.copyfile(pair/"summary.json",dest/"summary.json")
    with gzip.open(dest/"P0-comparability.gz","wb") as f:
        chunk=bytearray()
        for _,scope,key,_ in occurrences(pair):
            chunk.append(2*"BQU".index(scope)+int(bool(key)))
            if len(chunk)>=1<<16:f.write(chunk);chunk.clear()
        f.write(chunk)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("run","tools","inputs","self_diffs","micro","new_evidence","new_checks"):
        p.add_argument(name,type=Path)
    a=p.parse_args()
    runs,ev,checks=a.run.resolve(),a.new_evidence.resolve(),a.new_checks.resolve()
    ev.mkdir(parents=True,exist_ok=False);checks.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(runs/"plan.json",ev/"plan.json")
    (ev/"micro").mkdir()
    shutil.copyfile(a.micro/"summary.json",ev/"micro/summary.json")
    with tarfile.open(ev/"micro/raw.tar.gz","w:gz") as archive:
        archive.add(a.micro,arcname="micro")
    summaries={}
    for case in CASES:
        compact_self(a.self_diffs/case,ev/"self"/case)
        out=ev/"pairs"/case;out.mkdir(parents=True)
        d1=BASE/"reports/evidence/d1/runs/off"/case/"P0"
        with gzip.open(d1/"result.json.gz","rt") as f:
            reference,witness=json.load(f)
        oracle=runs/case/"oracle-1/work/native-learns.tsv"
        packed(oracle,out/"native-learns.tsv.gz")
        receipts=[];payloads={};checksums=[];resources=[]
        for mode,rep in [(m,i) for i in (1,2,3) for m in ("off","on")]+[("oracle",1)]:
            name=f"{mode}-{rep}"
            src=runs/case/name;dest=out/name;dest.mkdir()
            for filename in ("stdout","stderr"):packed(src/filename,dest/(filename+".gz"))
            for filename in ("run.json","result.json"):shutil.copyfile(src/filename,dest/filename)
            run=json.loads((src/"run.json").read_text())
            result,trace=interpret(run,(src/"stdout").read_text())
            if search_signature(result)!=search_signature(reference):raise ValueError(f"native search changed: {src}")
            rt=dict(mode=mode,repeat=rep,wall_s=run["wall_ns"]/1e9,rss_kib=run["peak_rss_kib"],
                    user_s=run["user_s"],system_s=run["system_s"],property_solve_s=result["queries"][0]["property_decider_solve_s"],
                    solver_s=result["native_timers_s"]["Solver"][0],exit_code=run["exit_code"],
                    trace_against_D1=trace_comparison(witness,trace))
            resources.append(rt)
            if mode!="on":continue
            proof=src/"knowledge.bin"
            logical,clocks=logical_sha(proof)
            if logical not in payloads:
                payloads[logical]=f"proof-{rep}.bin.gz"
                packed(proof,out/payloads[logical])
            receipts.append(dict(repeat=rep,raw_bytes=proof.stat().st_size,raw_sha256=digest(proof),logical_sha256=logical,
                compressed_payload=payloads[logical],footer_clocks=clocks))
            check=checks/case if rep==1 else checks/f"{case}-{rep}"
            check.mkdir()
            subprocess.run([a.tools/"check",proof,a.inputs/case/"inputs.txt",a.inputs/case/"mapped.txt",oracle,check],check=True)
            rt["proof_metrics"]=table(check/"metrics.tsv")
            for filename in ("learned.tsv","used.tsv","survivors.tsv"):
                if rep==1:packed(check/filename,out/(filename+".gz"))
                elif digest(check/filename)!=digest(checks/case/filename):
                    raise ValueError("separate repetitions produced different checked learning or invalidation")
            shutil.copyfile(check/"metrics.tsv",dest/"proof-metrics.tsv")
            checksums.append(digest(check/"learned.tsv"))
        save(out/"runs.json",dict(proofs=receipts,resources=resources,checked_learning_sha256=checksums))
        inspect(case,runs/case/"on-1",checks/case,a.self_diffs/case,out/"used-input-analysis.json")
        summary=table(checks/case/"metrics.tsv")
        summary["raw_bytes"]=receipts[0]["raw_bytes"]
        summary["compressed_bytes"]=(out/receipts[0]["compressed_payload"]).stat().st_size
        summary["median"]={m:{metric:statistics.median(r[metric] for r in resources if r["mode"]==m)
                        for metric in ("wall_s","rss_kib","solver_s","property_solve_s","user_s","system_s")} for m in ("off","on")}
        summary["logical_proof_variants"]=len(payloads)
        summaries[case]=summary
    save(ev/"summary.json",summaries)


if __name__=="__main__":main()
