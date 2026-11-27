"""Compute all pairwise deltas and engineering thresholds from the complete three-round matrix."""
import argparse,csv,json,shutil
from pathlib import Path
from statistics import median
from d42_prepare import read,save
from diff_d1 import digest
from run_stock import BASE

def tsv(path,rows):
    with path.open("w") as f:
        keys=list(dict.fromkeys(k for r in rows for k in r))
        w=csv.DictWriter(f,keys,delimiter="\t",lineterminator="\n");w.writeheader();w.writerows(rows)

def pair(before,after):
    delta=[(a-b)/1e9 for a,b in zip(before,after)]
    frac=[(a-b)/a for a,b in zip(before,after)]
    ratios=[a/b if b else None for a,b in zip(before,after)]
    return dict(seconds=delta,relative=frac,speedup=ratios,median_s=median(delta),range_s=[min(delta),max(delta)],
        median_relative=median(frac),positive=sum(v>0 for v in delta),median_speedup=median(ratios) if all(ratios) else None)

def grouped(v):return dict(median=median(v),min=min(v),max=max(v),rounds=v)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ("functional","performance","audit","clocks","d4","out"):p.add_argument(n,type=Path)
    p.add_argument("--stock-clocks",nargs=2,metavar=("ROUND_2","ROUND_3"),type=Path,
                   help="independent stock search-only observations; stock walls always use the original ELF")
    a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True)
    stage=read(BASE/"configs/d42-plan.json");gate=read(a.audit/"gate.json");assert gate["L1"]=="PASS"
    results=read(a.performance/"results.json");func=read(a.functional/"results.json");aud=read(a.audit/"dependency-equivalence.json")
    timers=[read(folder/"timers.json") for folder in (a.clocks,*(a.stock_clocks or []))]
    rawperf=[];pol=[];mapping=[];recording=[];deltas=[];classes=[]
    stats={};stats_search={};l2a={};l2b={};net1={};net2={};plans=stage["thresholds"]
    for case in stage["cases"]:
        e=aud[case];side=func[case]["1"];g=stats[case]={}
        for arm in ("Reference","Light-only","Mapping-only","Combined","record-cold","reuse"):
            r=side[arm]["P1"];tr=r["transport"]
            mapping.append(dict(case=case,arm=arm,**tr))
            pol.append(dict(case=case,arm=arm,eligible=r["selection"]["eligible"],selected=r["selection"]["chosen"],families=json.dumps(r["families"],sort_keys=True)))
            deltas.append(dict(case=case,arm=arm,**r["delta_ns"],rev_ns=tr["reverse_ns"],structural_ns=tr["structural_ns"]))
        cls=side["Combined"]["P1"]["transport"]
        classes.append(dict(case=case,births=e["births"],resident=e["resident"],pure_B=cls.get("permanent_B",0),mixed=cls.get("permanent_M",0),
            theory=cls.get("permanent_T",0),query=cls["query"],unknown=cls["unknown"],complete=cls["permanent"],mapped=cls["mapped"],eligible=cls["eligible"]))
        ordered=[results[case][str(i)] for i in range(1,4)];assert len(results[case])==3
        allrows=[("functional",0,side)]+[("paired",i,r) for i,r in enumerate(ordered,1)]
        for phase,round_,data in allrows:
            for mode,versions in data.items():
                for version,r in versions.items():
                    x=dict(phase=phase,round=round_,case=case,mode=mode,side=version,property=r["result"],wall_ns=r["wall_ns"],cpu_s=r["cpu_s"],
                        native_process_ns=r["process_ns"],seal_ns=r["seal_ns"],search_ns=r["search_ns"],restarts=r["restarts"],
                        solver_s=r["solver_s"],rss_kib=r["rss_kib"],**r["counts"],**r["root"])
                    if mode=="stock":
                        obs=max(0,round_-1) if len(timers)==3 else 0
                        q=timers[obs][case+"/"+version]
                        x.update(separate_stock_search_ns=q["search_ns"],separate_stock_restarts=q["restarts"],
                                 stock_observer_round=obs+1)
                    rawperf.append(x)
                    if version=="P0" and mode in ("record","reference"):
                        recording.append(dict(phase=phase,round=round_,case=case,mode=mode,wall_ns=r["wall_ns"],search_ns=r["search_ns"],
                            rss_kib=r["rss_kib"],proof_bytes=r["proof_bytes"],library_bytes=r["library_bytes"],seal_ns=r["seal_ns"],**r.get("export",{})))
        def arr(arm,version,k):return [r[arm][version][k] for r in ordered]
        cold,reuse=arr("record-cold","P1","search_ns"),arr("reuse","P1","search_ns")
        g["search"]=pair(cold,reuse)
        stock1,real1=arr("stock","P1","wall_ns"),arr("reuse","P1","wall_ns")
        g["wall"]=pair(stock1,real1)
        g["cycle"]=pair([p+q for p,q in zip(arr("stock","P0","wall_ns"),stock1)],[p+q for p,q in zip(arr("record","P0","wall_ns"),real1)])
        for k in ("sat_propagations","inclusive_conflicts"):
            g[k]=grouped([1-row["reuse"]["P1"]["counts"][k]/row["record-cold"]["P1"]["counts"][k] for row in ordered])
        rec={}
        for k in ("wall_ns","rss_kib","cpu_s"):
            before=[r["reference"]["P0"][k]-r["off"]["P0"][k] for r in ordered]
            after=[r["record"]["P0"][k]-r["off"]["P0"][k] for r in ordered]
            rr=[(b-s)/b for b,s in zip(before,after) if b>0]
            rec[k]=dict(audit_extra=grouped(before),light_extra=grouped(after),relative=grouped(rr) if len(rr)==3 else None)
        g["p0"]=rec
        l2a[case]=rec;old=e["baseline"];added=len(e["added"]);l2b[case]=added>=max(10,.1*old) if old else bool(e["added_hits"])
        g["work_threshold"]=max(g["sat_propagations"]["median"],g["inclusive_conflicts"]["median"])>=plans["search_work_reduction"]
        stats_search[case]=bool(e["main_hits"] and g["work_threshold"] and g["search"]["median_relative"]>=.05 and g["search"]["positive"]>=2)
        net1[case]=bool(g["wall"]["median_relative"]>=.05 and g["wall"]["positive"]>=2 and e["main_hits"] and
                        max(g["sat_propagations"]["median"],g["inclusive_conflicts"]["median"])>0)
        net2[case]=g["cycle"]["median_relative"]>=.05 and g["cycle"]["positive"]>=2
    def reduction(c,k):
        v=l2a[c][k]["relative"];return v["median"] if v else float("-inf")
    duo=["circular-buffer","airline_reservations_6"]
    light=any(reduction(c,"wall_ns")>.30 and reduction(c,"rss_kib")>.30 and
              reduction(peer,"wall_ns")>=-.10 and reduction(peer,"rss_kib")>=-.10 and aud[c]["equivalence"]["online_reclaimed"]>0
              for c,peer in (duo,duo[::-1]))
    repair=stage["cases"][:3];outcomes=dict(L1="PASS",**{k:("PASS" if v else "NOT_ACHIEVED") for k,v in (
        ("L2-A",light),("L2-B",any(l2b[c] for c in repair)),("L2-C",any(stats_search.values())),("L3.1",any(net1[c] for c in repair)),
        ("L3.2",any(net2[c] for c in repair)))})
    for file,rows in (("recording",recording),("delta-cost",deltas),("mapping",mapping),("classification",classes),("policies",pol),("performance",rawperf)):tsv(out/(file+".tsv"),rows)
    fixed=a.d4/"fib_updates_8/reuse/P1/native";rows=(fixed/"ready.tsv").read_text().splitlines()
    assert len(rows)==122 and rows[0].split()[-1]=="121"
    shutil.copyfile(fixed/"ready.tsv",out/"D4-fibonacci-121.tsv")
    save(out/"fixed-d4.json",dict(source="D4 release-runs/fib_updates_8/reuse/P1/native",sha256=digest(fixed/"ready.tsv"),eligible=121,
         hits_sha256=digest(fixed/"hits.tsv"),imports_sha256=digest(fixed/"imports.tsv")))
    save(out/"paired.json",stats);save(out/"audit.json",dict(gate=gate,case_search=stats_search,case_mapping=l2b,case_P1=net1,case_cycle=net2,outcomes=outcomes))
    save(out/"properties.json",dict(functional=read(a.functional/"properties.json"),paired=read(a.performance/"properties.json")))
    shutil.copyfile(a.audit/"dependency-equivalence.json",out/"dependency-equivalence.json")
    save(out/"identity-controls.json",{c:{k:e[k] for k in ("A1_A2","A3")} for c,e in aud.items() if "A3" in e})
    print(json.dumps(outcomes,indent=2))
if __name__=="__main__":main()
