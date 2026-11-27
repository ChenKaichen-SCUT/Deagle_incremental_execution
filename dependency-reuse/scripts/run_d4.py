"""Run the preregistered single D4 end-to-end comparison on three frozen pairs."""
import argparse
import json
from pathlib import Path
import sys
import time

from diff_d1 import digest
from package_d1 import logical, metrics, trace_comparison
from run_stock import BASE, run, save
from summarize_stock import interpret


def property_contract(result):
    return logical({k:result[k] for k in ("properties","cProverStatus","classification","target_status",
        "unwinding_property_ids","unwinding_iterations","unwinding_stop_or_warning","enabled_unwinding_assertions",
        "vcc_messages","adapter_query_count","closure_completion_count","warnings","native_warning_lines")})


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("binary","tools","stock_timer","new_directory"):p.add_argument(key,type=Path)
    p.add_argument("--diagnose-case",choices=("fib_updates_8","circular-buffer","airline_reservations_6"))
    a=p.parse_args()
    exe,tools,timer,d=(v.resolve() for v in (a.binary,a.tools,a.stock_timer,a.new_directory))
    stock_info=json.loads((BASE/"configs/build.json").read_text())
    stock=Path(stock_info["binary_path"]);py=Path(sys.executable).resolve()
    if digest(stock)!=stock_info["binary_sha256"]:raise ValueError("stock binary differs from lock")
    cases=json.loads((BASE/"bench/manifest.json").read_text())
    spec_plan=json.loads((BASE/"configs/d4-plan.json").read_text())
    order=[a.diagnose_case] if a.diagnose_case else spec_plan["order"]
    modes=["reuse"] if a.diagnose_case else spec_plan["modes"]
    d.mkdir(parents=True,exist_ok=False)
    save(d/"plan.json",dict(policy=spec_plan,diagnostic=bool(a.diagnose_case),schedule=[
        [c,m,v] for c in order for m in modes for v in spec_plan["versions"]],stock_sha256=digest(stock),
        native_sha256=digest(exe),stock_timer_sha256=digest(timer) if timer.exists() else None,
        input_lock_sha256=digest(BASE/"bench/manifest.json")))
    summary={}
    for case in order:
        reference={};reftrace={};arms={}
        for mode in modes+([] if a.diagnose_case else ["stock-search-observer"]):
            arm=d/case/mode;rows={}
            for side in (("P1",) if mode=="stock-search-observer" else ("P0","P1")):
                folder=arm/side
                flags=[];spec=dict(cases[case])
                command=stock if mode=="stock" else exe
                if mode=="stock-search-observer":command=timer
                elif mode=="off":flags=["--d4-search-log",str(folder/"search.tsv")]
                elif mode in ("record-cold","reuse"):
                    command=py
                    flags=[str(BASE/"scripts/d4.py"),"record" if side=="P0" else mode,
                           "--binary",str(exe),"--tools",str(tools),"--out",str(folder/"native")]
                    if side=="P1":flags+=["--library",str(arm/"P0/native")]
                    for filename in spec["inputs"][side]:flags+=["--source",filename]
                    flags+=["--"]
                spec["argv"]=[*flags,*spec["argv"]]
                run(command,spec,case,side,folder,digest(command))
                meta=json.loads((folder/"run.json").read_text())
                if meta["timed_out"] or meta["exit_code"] not in (0,10):
                    raise ValueError(f"{case}/{mode}/{side} exit {meta['exit_code']}, see raw logs")
                result,trace=interpret(meta,(folder/"stdout").read_text())
                save(folder/"result.json",result)
                if mode=="stock":
                    reference[side]=result;reftrace[side]=trace
                elif not a.diagnose_case:
                    if property_contract(result)!=property_contract(reference[side]):
                        raise ValueError(f"property/unwinding mismatch in {folder}")
                    save(folder/"trace-comparison.json",trace_comparison(reftrace[side],trace))
                    if (mode!="reuse" or side=="P0") and metrics(result)!=metrics(reference[side]):
                        raise ValueError(f"cold native search differs in {folder}")
                qt=result["queries"]
                if len(qt)!=1 or result["target_status"]!=("FAILURE" if side=="P0" else "SUCCESS"):
                    raise ValueError(f"unexpected frozen query in {folder}")
                searchfile=folder/("work/stock-search.tsv" if mode=="stock-search-observer" else
                    "native/search.tsv" if mode in ("reuse","record-cold") else "search.tsv")
                search=searchfile.read_text().splitlines() if searchfile.exists() else None
                rows[side]=dict(wall_s=meta["wall_ns"]/1e9,peak_rss_kib=meta["peak_rss_kib"],
                    verifier_status=result["target_status"],exit_code=meta["exit_code"],counts=qt[0]["native_cumulative"],
                    property_decider_s=qt[0]["property_decider_solve_s"],
                    search_ns=sum(int(x.split()[0]) for x in search) if search else None,
                    restarts=sum(int(x.split()[1]) for x in search) if search else None)
            arms[mode]=rows
            if "P0" in rows:rows["cycle_s"]=rows["P0"]["wall_s"]+rows["P1"]["wall_s"]
        summary[case]=arms
        save(d/"summary.json",summary)


if __name__=="__main__":main()
