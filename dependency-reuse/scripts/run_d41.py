"""Run the predeclared D4.1 controls and policy arms, once each, in fresh native processes."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import sys
from diff_d1 import digest
from package_d1 import logical,metrics,trace_comparison
from run_stock import BASE,run,save
from summarize_stock import interpret
from run_d4 import property_contract


def read(path):return json.loads(path.read_text())


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("tree","tools","d4_tree","d4_tools","stock_timer","out"):p.add_argument(k,type=Path)
    p.add_argument("--pilot",action="store_true")
    p.add_argument("--resume",action="store_true",help="re-read every completed cell and validate its original process receipt")
    a=p.parse_args()
    tree,tools,d4,oldtools,timer,root=[x.resolve() for x in (a.tree,a.tools,a.d4_tree,a.d4_tools,a.stock_timer,a.out)]
    exe=tree/"src/cbmc/deagle_exe";old=d4/"src/cbmc/deagle_exe";stock=Path(read(BASE/"configs/build.json")["binary_path"])
    d4status=read(BASE/"reports/D4-status.json")
    assert digest(old)==d4status["native_elf_sha256"] and digest(stock)==d4status["stock_elf_sha256"]
    assert digest(timer)==d4status["stock_search_observer_sha256"]
    specs=read(BASE/"bench/manifest.json");plan=read(BASE/"configs/d41-plan.json")
    root.mkdir(parents=True,exist_ok=a.resume)
    schedule=dict(preregistered=plan,diagnostic=a.pilot,new_elf=digest(exe),d4_elf=digest(old),stock_elf=digest(stock),
                  stock_timer=digest(timer),input_lock=digest(BASE/"bench/manifest.json"))
    if a.resume:assert read(root/"plan.json")==schedule
    else:save(root/"plan.json",schedule)
    summary={}
    for case in (plan["cases"][:1] if a.pilot else plan["cases"]):
        data=summary[case]={};ref={};traces={}
        def process(label,side,command,prefix,source=None):
            wd=root/case/label/side
            sp=dict(specs[case]);sp["argv"]=[*map(str,prefix),*sp["argv"]]
            if not (a.resume and (wd/"run.json").is_file()):
                run(command,sp,case,side,wd,digest(command))
            else:
                original=read(wd/"run.json")
                assert original["argv"]==[str(command),*sp["argv"]] and original["binary_sha256"]==digest(command)
                assert all(original[k+"_sha256"]==digest(wd/k) for k in ("stdout","stderr"))
                assert original["input_sha256"]=={name:sp["files_sha256"][src] for name,src in sp["inputs"][side].items()}
            meta=read(wd/"run.json")
            if meta["timed_out"] or meta["exit_code"]!=(10 if side=="P0" else 0):
                raise ValueError(f"{case}/{label}/{side} failed; inspect raw stdout, stderr and preparation")
            result,trace=interpret(meta,(wd/"stdout").read_text());save(wd/"result.json",result)
            if label=="stock":ref[side]=result;traces[side]=trace
            else:
                # A legitimate import-time contradiction can finish before entering search.
                contract=property_contract(result);expected=property_contract(ref[side])
                for c in (contract,expected):c.pop("closure_completion_count")
                assert contract==expected,(case,label,side,"property/unwind")
                t=trace_comparison(traces[side],trace);save(wd/"trace-comparison.json",t)
                assert all(v["visible_steps_equal"] for v in t.values()),(case,label,"visible trace")
                if side=="P0" or label in ("off","clock","none"):
                    assert metrics(result)==metrics(ref[side]),(case,label,side,"cold behavior")
            native=wd/"native";q=result["queries"][0]
            watch=wd/"search.tsv" if label=="off" else wd/"work/stock-search.tsv" if label=="clock" else native/"search.tsv"
            ns=sum(int(l.split()[0]) for l in watch.read_text().splitlines()) if watch.exists() else None
            counts=q["native_cumulative"] or {}
            work=native/"cumulative-work.tsv";rootwork={}
            if (native/"import-time.tsv").exists():
                rootwork={k:int(v) for k,v in (l.split() for l in (native/"import-time.tsv").read_text().splitlines())}
            if work.exists():
                vals=[int(v) for v in work.read_text().splitlines()[-1].split()]
                observed=dict(zip(("sat_conflicts","decisions","sat_propagations","theory_propagations","theory_cycle_conflicts"),vals))
                assert all(counts.get(k,v)==v for k,v in observed.items())
                counts={**counts,**observed}
            total_conf=counts.get("sat_conflicts",0)+rootwork.get("root_conflicts",0)-rootwork.get("root_conflicts_counter_delta",0)
            # Native counters already include root propagation and theory cycles.
            row=dict(wall_s=meta["wall_ns"]/1e9,search_s=ns/1e9 if ns is not None else None,rss_kib=meta["peak_rss_kib"],
                counts=counts,total_conflicts=total_conf,root=rootwork,property=result["target_status"],producer=source)
            if (native/"proof.bin").exists():row["proof_bytes"]=(native/"proof.bin").stat().st_size
            if (native/"imports.tsv").exists():
                by_family={}
                with (native/"imports.tsv").open() as f:
                    for r in csv.DictReader(f,delimiter="\t"):
                        c=by_family.setdefault(r["family"],Counter());c["selected"]+=1;c[r["disposition"]]+=1
                        for k in ("watch_unit","watch_conflict","analyze","minimize"):c[k]+=int(r[k])
                        c["rows_used"]+=any(int(r[k]) for k in ("watch_unit","watch_conflict","analyze","minimize"))
                row["families"]=by_family
                row["selection"]={k:int(v) for k,v in (l.split() for l in (native/"selection.tsv").read_text().splitlines())}
                row["preparation_ns"]=read(native/"delta.json")["timings_ns"]
            data.setdefault(label,{})[side]=row
            if side=="P1" and source:row["cycle_s"]=data[source]["P0"]["wall_s"]+row["wall_s"]
            save(root/"summary.json",summary)
        for label,binary in (("stock",stock),("off",exe)):
            for side in ("P0","P1"):
                stage=root/case/label/side
                process(label,side,binary,["--d4-search-log",stage/"search.tsv"] if label=="off" else [],label if side=="P1" else None)
        process("clock","P1",timer,[])
        def verifier(label,side,src,options,legacy=False):
            bin,t,script=(old,oldtools,d4) if legacy else (exe,tools,tree)
            dest=root/case/label/side/"native"
            flags=[script/"dependency-reuse/scripts/d4.py","record" if side=="P0" else "reuse","--binary",bin,"--tools",t,"--out",dest,*options]
            if side=="P1":flags+=["--library",root/case/src/"P0/native"]
            for name in specs[case]["inputs"][side]:flags+=["--source",name]
            process(label,side,Path(sys.executable).resolve(),[*flags,"--"],src if side=="P1" else None)
        verifier("d4","P0",None,[],True);verifier("d4","P1","d4",[],True)
        # Identical ELF with the old rule set. AB and compact each have their own recorded P0.
        for label,opts in (("legacy",[]),("A",["--triplets"]),("eager",["--triplets","--identities","--eager"]),("AB",["--triplets","--identities"]),
                            ("compact",["--triplets","--identities","--compact"])):
            verifier(label,"P0",None,opts)
        for label,src,mapping in (("legacy","legacy","d4"),("A","A","d4"),("AB-old","AB","d4"),("AB","AB","d41"),
                                  ("compact-full","compact","d41")):
            verifier(label,"P1",src,["--mapping",mapping,"--policy","all"])
        for policy in plan["fixed_selection"]:
            verifier(policy,"P1","compact",["--mapping","d41","--diff","focused","--policy",policy])
        pools=[root/case/l/"P1/native/eligible.tsv" for l in ("AB","compact-full",*plan["fixed_selection"])]
        assert len({digest(f) for f in pools})==1,(case,"eligibility changed across cost/policy controls")
        assert digest(root/case/"A/P1/native/eligible.tsv")==digest(root/case/"AB-old/P1/native/eligible.tsv")
        assert data["legacy"]["P1"]["counts"]==data["d4"]["P1"]["counts"]
        for l in ("AB","compact-full"):assert data[l]["P1"]["counts"]==data["all"]["P1"]["counts"]
    print("completed D4.1 matrix",flush=True)


if __name__=="__main__":main()
