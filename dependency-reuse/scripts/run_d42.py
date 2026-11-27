"""Run the locked cohort from fresh processes. Performance requires the functional audit receipt."""
import argparse,csv,json,sys,time
from collections import Counter
from pathlib import Path
from cases42 import load
from d42_prepare import read,save
from diff_d1 import digest
from package_d1 import metrics,trace_comparison
from record42 import record
from run_stock import BASE,run
from run_d4 import property_contract
from summarize_stock import interpret


def snapshot(folder):
    meta=read(folder/"run.json")
    if meta["timed_out"] or meta["exit_code"] not in (0,10):raise ValueError(f"native failure at {folder}")
    result,_=interpret(meta,(folder/"stdout").read_text());save(folder/"result.json",result)
    native=folder/"native";clock=native/"search.tsv" if native.is_dir() else folder/"search.tsv"
    if not clock.exists() and (folder/"work/stock-search.tsv").exists():clock=folder/"work/stock-search.tsv"
    q=result["queries"];counts=dict(q[-1]["native_cumulative"] or {});r={}
    if (native/"import-time.tsv").exists():
        r={k:int(v) for k,v in (l.split() for l in (native/"import-time.tsv").read_text().splitlines())}
        values=list(map(int,(native/"cumulative-work.tsv").read_text().splitlines()[-1].split()))
        for k,v in zip(("sat_conflicts","decisions","sat_propagations","theory_propagations","theory_cycle_conflicts"),values):
            if k in counts and counts[k]!=v:raise ValueError("cumulative work differs")
            counts[k]=v
    if "sat_conflicts" in counts:counts["inclusive_conflicts"]=counts["sat_conflicts"]+r.get("root_conflicts",0)-r.get("root_conflicts_counter_delta",0)
    times=[list(map(int,l.split())) for l in clock.read_text().splitlines()] if clock.exists() else []
    row=dict(wall_ns=meta.get("inclusive_wall_ns",meta["wall_ns"]),process_ns=meta["wall_ns"],seal_ns=meta.get("seal_ns",0),
             cpu_s=meta["user_s"]+meta["system_s"]+meta.get("seal_cpu_ns",0)/1e9,rss_kib=meta["peak_rss_kib"],counts=counts,root=r,
             solver_s=sum(t["property_decider_solve_s"] for t in q),
             search_ns=sum(v[0] for v in times) if times or r else None,
             restarts=sum(max(0,v[1]-1) for v in times) if times or r else None,
             result=result["target_status"],contract=property_contract(result))
    if (native/"proof.bin").exists():
        row["proof_bytes"]=(native/"proof.bin").stat().st_size
        row["library_bytes"]=sum((native/f).stat().st_size for f in read(native/"receipt42.json")["files"])
        if (native/"proof.bin.timing.tsv").exists():row["export"]={k:int(v) for k,v in (l.split() for l in (native/"proof.bin.timing.tsv").read_text().splitlines())}
    if (native/"imports.tsv").exists():
        fam={}
        with (native/"imports.tsv").open() as f:
            for item in csv.DictReader(f,delimiter="\t"):
                g=fam.setdefault(item["family"],Counter());g["rows"]+=1;g[item["disposition"]]+=1
                for k in ("watch_unit","watch_conflict","analyze","minimize"):g[k]+=int(item[k])
                g["distinct_hits"]+=any(int(item[k]) for k in ("watch_unit","watch_conflict","analyze","minimize"))
        row["families"]=fam;row["selection"]=read(native/"policy.json")
        row["delta_ns"]=read(native/"delta42.json")["timings_ns"]
        row["transport"]={k:(int(v) if k!="stop" else v) for k,v in (l.split() for l in (native/"transport.tsv").read_text().splitlines())}
    return row


def plain(binary,spec,case,side,folder,timer=False):
    opts=["--d4-search-log",str(folder/"search.tsv")] if timer else []
    run(binary,{**spec,"argv":[*opts,*spec["argv"]]},case,side,folder,digest(binary))

def boundary(binary,tools,spec,case,folder,lib,mode,mapping,policy):
    out=folder/"native";out.mkdir(parents=True)
    cfg=dict(case=case,mapping=mapping,policy=policy)
    if case=="airline_reservations_6":
        cfg["source_patch"]=dict(file="program.c",patch=str(BASE/"bench"/case/"patch.diff"),
            patch_sha256=spec["files_sha256"]["patch.diff"],new_sha256=spec["files_sha256"][spec["inputs"]["P1"]["program.c"]])
    t=time.monotonic_ns();save(out/"control42.json",cfg)
    setup=time.monotonic_ns()-t
    flags=["--d4-load",lib,"--d4-mode",mode,"--d4-out",out,"--d4-tools",tools,"--d41-identities","--d4-search-log",out/"search.tsv"]
    run(binary,{**spec,"argv":[*map(str,flags),*spec["argv"]]},case,"P1",folder,digest(binary))
    meta=read(folder/"run.json");meta["inclusive_wall_ns"]=meta["wall_ns"]+setup;meta["control_write_ns"]=setup
    save(folder/"run.json",meta)
    if meta["exit_code"] in (0,10) and not (out/"imports.tsv").exists():raise RuntimeError("missing actual native import receipt")

def compare(reference,folder,trajectory,encoding=None):
    def result(root):return interpret(read(root/"run.json"),(root/"stdout").read_text())
    gold,t0=result(reference);actual,t1=result(folder)
    a,b=map(property_contract,(gold,actual));a.pop("closure_completion_count");b.pop("closure_completion_count")
    if a!=b:raise ValueError(f"property/unwind mismatch: {folder}")
    traces=trace_comparison(t0,t1)
    if any(not r["visible_steps_equal"] for r in traces.values()):raise ValueError(f"observable trace changed: {folder}")
    explained=False
    if trajectory and metrics(gold)!=metrics(actual):
        if not encoding:raise ValueError(f"cold search changed: {folder}")
        oldq=[q["native_cumulative"] for q in gold["queries"]]
        newq=[q["native_cumulative"] for q in actual["queries"]]
        if oldq!=encoding["stock"] or newq!=encoding["manifest"] or not encoding["alpha"]["exact_all_scopes"]:
            raise ValueError(f"trajectory differs from independent same-encoding observers: {folder}")
        import copy
        adjusted=copy.deepcopy(actual)
        for x,y in zip(adjusted["queries"],gold["queries"]):
            for k in ("native_cumulative","native_delta_from_previous_snapshot"):x[k]=y[k]
        if metrics(gold)!=metrics(adjusted):raise ValueError(f"additional native difference in {folder}")
        explained=True
    return {"properties":a,"traces":traces,"cold_trajectory_checked":trajectory,"verified_query_renaming":explained}

def matrix(binary,tools,root,action,gate,chosen_cases=None,encoding=None):
    plan=read(BASE/"configs/d42-plan.json");specs=load();stockinfo=read(BASE/"configs/build.json")
    stock=Path(stockinfo["binary_path"]);assert digest(stock)==stockinfo["binary_sha256"]
    if action=="performance":
        approved=read(gate);assert approved["L1"]=="PASS" and approved["binary"]==digest(binary)
        from d42_prepare import tool_hashes
        assert approved["tools"]==tool_hashes(tools) and set(approved["cases"])==set(specs) and not chosen_cases
    if root.exists():raise ValueError("use a fresh directory for every matrix, including failed runs")
    root.mkdir(parents=True);save(root/"plan.json",dict(action=action,lock=digest(BASE/"configs/d42-plan.json"),native=digest(binary),
        stock=digest(stock),cases=list(chosen_cases or specs),gate=digest(gate) if gate else None))
    results={};properties={}
    for c in chosen_cases or specs:
        s=specs[c]
        rounds=plan["order"] if action=="performance" else [["stock","off","record","reference","Reference","Light-only","Mapping-only","Combined","record-cold","reuse"]]
        for i,order in enumerate(rounds,1):
            arm=root/c/str(i);data=results.setdefault(c,{})[i]={};folders=[]
            for mode in order:
                side0=arm/mode/"P0";side1=arm/mode/"P1"
                if mode in ("stock","off"):
                    for side,folder in (("P0",side0),("P1",side1)):
                        plain(stock if mode=="stock" else binary,s,c,side,folder,mode=="off");folders.append((mode,side,folder,True))
                elif mode in ("record","reference"):
                    record(binary,c,"light" if mode=="record" else "audit",side0,tools);folders.append((mode,"P0",side0,True))
                else:
                    variants={"Reference":("reference","semantic","all"),"Light-only":("record","semantic","all"),
                        "Mapping-only":("reference","structure","all"),"Combined":("record","structure","all"),
                        "record-cold":("record","structure","top512"),"reuse":("record","structure","top512")}
                    src,mapping,policy=variants[mode]
                    boundary(binary,tools,s,c,side1,arm/src/"P0/native","record-cold" if mode=="record-cold" else "reuse",mapping,policy)
                    folders.append((mode,"P1",side1,mode=="record-cold"))
                for label,side,folder,_ in folders:
                    if label==mode:data.setdefault(mode,{})[side]=snapshot(folder)
                save(root/"results.json",results)
            for mode,side,folder,trajectory in folders:
                certificate=None
                if encoding and c=="fib-snapshot-11" and mode in ("record","reference","record-cold"):
                    certificate=read(encoding)[side]
                properties[f"{c}/{i}/{mode}/{side}"]=compare(arm/"stock"/side,folder,trajectory,certificate)
            save(root/"properties.json",properties)
    return results


if __name__=="__main__":
    a=argparse.ArgumentParser(__doc__)
    a.add_argument("action",choices=("functional","performance"))
    for name in ("binary","tools","out"):a.add_argument(name,type=Path)
    a.add_argument("--gate",type=Path);a.add_argument("--cases",nargs="+")
    a.add_argument("--encoding",type=Path,help="independent whole-model and trajectory receipts for the historical Q encoding")
    p=a.parse_args();matrix(p.binary.resolve(),p.tools.resolve(),p.out.resolve(),p.action,p.gate,p.cases,p.encoding)
