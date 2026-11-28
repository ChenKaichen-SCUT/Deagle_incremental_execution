"""Recompute D4.3-E costs, uses, preserved properties and gates from raw per-process receipts."""
import argparse
import json
import math
from pathlib import Path
from statistics import median

from audit_d43e import HIT_NAMES, Reference, correctness, record_stats, same_in_order
from cases42 import load
from compact43 import require
from diff_d1 import digest
from run_d43d import read
from run_d43e import rotation, trigger
from run_stock import BASE, save
from summarize_d43d import phase, write


ARMS = (("stock","P0"),("stock","P1"),("off","P0"),("off","P1"),("light-quality","P0"),
        ("light-no-quality","P0"),("compact","P0"),("compact-cold","P1"),("compact-reuse","P1"))
PRIOR_SUBSTANTIAL={"circular-buffer","airline_reservations_6","fib-snapshot-11"}


def describe(values):
    if not values:
        return None
    return dict(median=median(values),minimum=min(values),maximum=max(values),positive=sum(v>0 for v in values),n=len(values))


def work(case,n,mode,side,arm):
    folder=arm/mode/side
    row=phase(case,mode,side,folder,arm/"stock-clock")
    require(read(folder/"run.json")["cpu_affinity"]==[0],"solver not pinned")
    row=dict(round=n,**row)
    native=folder/"native"
    clock=arm/"stock-clock"/side/"work/stock-search.tsv" if mode=="stock" else native/"search.tsv"
    row["restarts"]=sum(max(0,int(line.split()[1])-1) for line in clock.read_text().splitlines())
    if mode.startswith("light-"):
        cost=read(folder/"cost.json")
        require(cost["process_ns"]==row["process_ns"] and cost["total_ns"]==cost["seal_ns"]+row["process_ns"],
                "Light timing composition")
        quality_file="proof.bin.quality.tsv"
        require((native/quality_file).is_file()==(mode=="light-quality")
                and (quality_file in cost["files"])==(mode=="light-quality"),"Light quality disposition")
        row.update(P0_seal_ns=cost["seal_ns"],wall_ns=cost["total_ns"],library_bytes=cost["library_bytes"],
                   proof_bytes=cost["files"]["proof.bin"]["bytes"],model_bytes=cost["files"]["model.tsv"]["bytes"],
                   quality_bytes=cost["files"].get(quality_file,{}).get("bytes",0))
    return row


def verify_schedule(root,cases,rounds):
    expected=[]
    for n in range(1,rounds+1):
        for case in cases:
            producer=False
            for mode in rotation(n):
                if mode.startswith("compact-") and not producer:
                    expected.append((n,case,"compact","P0"));producer=True
                sides=("P0","P1") if mode in ("stock","off") else ("P0",) if mode.startswith("light-") else ("P1",)
                expected.extend((n,case,mode,side) for side in sides)
    formal_end=len(expected)
    for n in range(1,rounds+1):
        for c in cases:
            expected.extend((n,c,"stock-clock",side) for side in ("P0","P1"))
    observed=[json.loads(l) for l in (root/"schedule.jsonl").read_text().splitlines()]
    require(len(observed)==len(expected),"schedule length")
    previous=0;failed=[]
    for (n,c,m,s),event in zip(expected,observed):
        output=root/"matrix"/c/str(n)/m/s
        outcome=read(output/"outcome.json")
        label=f"{n} {c} {m}/{s}"
        require(label==event["sample"]==outcome["sample"] and previous<=event["start_ns"]==outcome["start_ns"]
                <=outcome["end_ns"],"overlap or rotation mismatch: "+label)
        previous=outcome["end_ns"]
        if not outcome["ok"]:
            failed.append(outcome)
    return dict(primary_samples=formal_end,clock_only_samples=len(expected)-formal_end,
                all_serial=True,cpu=0,failures=failed)


def paired(rows):
    modes={r["mode"]+r["side"]:r for r in rows}
    def wall(m):
        return modes[m]["wall_ns"]
    def time_diff(a,b,key):
        return modes[a][key]-modes[b][key]
    old0,old1=wall("stockP0"),wall("stockP1")
    off0,off1=wall("offP0"),wall("offP1")
    cp,cn=wall("compactP0"),wall("compact-reuseP1")
    cold=wall("compact-coldP1")
    quality,noqual=wall("light-qualityP0"),wall("light-no-qualityP0")
    extra=cp-off0; qe=quality-off0; ne=noqual-off0
    return dict(stock_P0_ns=old0,off_P0_ns=off0,Light_quality_P0_ns=quality,Light_no_quality_P0_ns=noqual,
                compact_P0_ns=cp,stock_P1_ns=old1,off_P1_ns=off1,cold_P1_ns=cold,reuse_P1_ns=cn,
                stock_cycle_ns=old0+old1,reuse_cycle_ns=cp+cn,
                extra_compact_vs_stock_ns=cp-old0,extra_compact_vs_off_ns=extra,
                extra_quality_vs_off_ns=qe,extra_no_quality_vs_off_ns=ne,
                quality_history_cost_ns=quality-noqual,extra_saved_vs_quality_ns=quality-cp,
                extra_saved_vs_no_quality_ns=noqual-cp,off_minus_stock_P0_ns=off0-old0,off_minus_stock_P1_ns=off1-old1,
                off_minus_stock_P0_to_root_ns=time_diff("offP0","stockP0","model_to_root_ns"),
                off_minus_stock_P1_to_root_ns=time_diff("offP1","stockP1","model_to_root_ns"),
                search_gain_ns=time_diff("compact-coldP1","compact-reuseP1","search_ns"),
                cold_minus_reuse_full_ns=cold-cn,P1_gain_ns=old1-cn,cycle_gain_ns=old0+old1-cp-cn,
                P1_fraction=(old1-cn)/old1,cycle_fraction=(old0+old1-cp-cn)/(old0+old1),
                conflict_saving=time_diff("compact-coldP1","compact-reuseP1","inclusive_conflicts"),
                propagation_saving=time_diff("compact-coldP1","compact-reuseP1","sat_propagations"),
                decision_saving=time_diff("compact-coldP1","compact-reuseP1","decisions"),
                theory_propagation_saving=time_diff("compact-coldP1","compact-reuseP1","theory_propagations"),
                theory_cycle_saving=time_diff("compact-coldP1","compact-reuseP1","theory_cycle_conflicts"))


def summarize_costs(samples,resolution_ns):
    noise=max(resolution_ns,max(r["off_P0_ns"] for r in samples)-min(r["off_P0_ns"] for r in samples))
    keys=[k for k in samples[0] if k not in ("round","case")]
    result={k:describe([r[k] for r in samples]) for k in keys}
    for r in samples:
        r["denominator_noise_floor_ns"]=noise
    for name,column in (("quality","extra_quality_vs_off_ns"),("no_quality","extra_no_quality_vs_off_ns")):
        key="recording_reduction_vs_"+name
        eligible=all(r[column]>noise for r in samples)
        for r in samples:
            r[key]=1-r["extra_compact_vs_off_ns"]/r[column] if eligible else None
        result[key]=describe([r[key] for r in samples]) if eligible else None
    result["denominator_noise_floor_ns"]=noise
    return result


def evaluate(all_pairs,funnels,trial_count,initial):
    p=math.ceil(trial_count*2/3)
    recording={}
    for ref in ("quality","no_quality"):
        recording[ref]=[]
        for c in PRIOR_SUBSTANTIAL:
            x=all_pairs[c]["recording_reduction_vs_"+ref]
            if x and x["median"]>=.5 and x["positive"]>=p:
                recording[ref].append(c)
        recording[ref].sort()
    increased={}
    for key in ("P1","cycle"):
        increased[key]=[]
        for case,o in all_pairs.items():
            x=o[key+"_fraction"]
            if (case!="fib-snapshot-11" and trial_count==5 and initial[case][key]["trigger"]
                    and x["median"]>=.05 and x["positive"]>=4):
                increased[key].append(case)
    hist=all_pairs["fib-snapshot-11"]
    history=[s for s in ("P1","cycle") if trial_count==5 and initial["fib-snapshot-11"][s]["trigger"]
             and hist[s+"_fraction"]["median"]>=.05 and hist[s+"_fraction"]["positive"]>=4]
    real={r["case"] for r in funnels if r["family"]=="M" and r["attached"] and r["distinct_hits"]
          and r["case"]!="fib-snapshot-11"}
    return dict(L1="PASS",L2_B="PASS" if real else "NOT_ACHIEVED",
        mixed_repair_cases=sorted(real),L2_C="PASS" if recording["quality"] else "NOT_ACHIEVED",
        L2_C_vs_original_Light_quality=recording["quality"],controlled_L2_C_vs_Light_no_quality=recording["no_quality"],
        L3_1="PASS" if increased["P1"] else "NOT_ACHIEVED",L3_2="PASS" if increased["cycle"] else "NOT_ACHIEVED",
        real_net_benefit_cases=increased,historical_confirmations=history,
        ablation_required=bool(increased["P1"] or increased["cycle"]),
        conclusion=("CONFIRMED_REPAIR_NET_GAIN" if increased["P1"] or increased["cycle"] else
                    "RECORDING_CHEAPER_NO_NET_GAIN" if recording["quality"] else "CORRECT_BUT_NO_NET_GAIN"))


def summarize(root,d_raw,B,old,out):
    cases=list(load());out.mkdir(parents=True,exist_ok=False)
    done=read(root/"timing-complete.json"); rounds=done["rounds"]
    require(rounds in (3,5),"wrong round count")
    sched=verify_schedule(root,cases,rounds); save(out/"schedule-check.json",sched)
    if sched["failures"]:
        retained=[]
        for outcome in sorted((root/"matrix").glob("*/*/*/*/outcome.json")):
            f=outcome.parent; row=read(outcome)
            if (f/"run.json").is_file():
                meta=read(f/"run.json")
                row.update({k:meta.get(k) for k in ("exit_code","timed_out","wall_ns","seal_ns","setup_ns","peak_rss_kib")})
            if (f/"cost.json").is_file():
                row["seal_ns"]=read(f/"cost.json")["seal_ns"]
            retained.append(row)
        write(out,"all-sample-outcomes.tsv",retained)
        save(out/"gate.json",dict(L1="INCOMPLETE",failures=sched["failures"],performance_claims=False))
        raise ValueError("incomplete timed samples; all failures retained")
    dec=trigger(root/"matrix",cases)
    require(dec==read(root/"confirmation.json") and rounds==(5 if dec["extend"] else 3),"confirmation mismatch")
    save(out/"confirmation.json",dec)
    ref=Reference(d_raw,B,old,out)
    manifest=read(root/"manifest.json")
    lock=read(BASE/"reports/evidence/d43d/build.json")
    require(manifest["approved_base"]=="ef76e75467b011058e7ff46d4fbc9552f499bf1d"
            and manifest["stock"]==lock["unmodified_stock_elf_sha256"]
            and manifest["build"]==lock["production_elf_sha256"]
            and manifest["observer"]==lock["stock_clock_observer_elf_sha256"]
            and manifest["workers"]==lock["production_worker"]["names_and_sha256"]
            and manifest["plan_sha256"]==digest(BASE/"configs/d43e-execution.json")
            and manifest["parent_plan_sha256"]==digest(BASE/"configs/d43-plan.json"),"approved configuration")
    inherited={}
    for path in ("D4.3-C-status.json","D4.3-D-status.json","evidence/d43d/gate.json","evidence/d43d/access.json"):
        inherited[path]=digest(BASE/"reports"/path)
    save(out/"build-isolation.json",dict(manifest=manifest,inherited_gate_sha256=inherited,
        C_gate=read(BASE/"reports/D4.3-C-status.json")["gate"],
        D_gate=read(BASE/"reports/D4.3-D-status.json")["gate"],
        inherited_D_access=read(BASE/"reports/evidence/d43d/access.json"),
        stock_clocks="Phase clocks/restarts only from a separately executed trajectory-matched observer."))
    specs=load()
    runs=[];cycles=[];funnel=[];pairs=[];checks={};stat={};provenance={};summaries={};record_rss={}
    for c in cases:
        checks[c]={};stat[c]={};provenance[c]={};series=[]
        for n in range(1,rounds+1):
            case_round={"case":c,"round":n};folder=root/"matrix"/c/str(n)
            for mode,side in (*ARMS,("stock-clock","P0"),("stock-clock","P1")):
                meta=read(folder/mode/side/"run.json")
                expected={k:specs[c]["files_sha256"][v] for k,v in specs[c]["inputs"][side].items()}
                elf=manifest["stock" if mode=="stock" else "observer" if mode=="stock-clock" else "build"]
                require(meta["input_sha256"]==expected and meta["binary_sha256"]==elf
                        and meta["cpu_affinity"]==[0] and meta["limits"]==specs[c]["limits"],
                        f"input/build/CPU/limit mismatch {c} {n} {mode} {side}")
            checks[c][n]=correctness(folder,c)
            info,families=same_in_order(folder,c,n,ref)
            provenance[c][n]=info
            stats=record_stats(folder/"compact/P0");stat[c][n]=stats
            funnel.extend({**case_round,**r} for r in families)
            samples=[]
            for mode,side in ARMS:
                row=work(c,n,mode,side,folder)
                if mode=="compact":
                    row.update(library_bytes=stats["library_bytes"],proof_bytes=stats["dense_bytes"],model_bytes=stats["model_bytes"])
                if mode=="off":
                    row["model_bytes"]=(folder/mode/side/"native/model.tsv").stat().st_size
                for k in ("selected","attached","distinct_hits",*HIT_NAMES):
                    if mode.startswith("compact-"):
                        row[k]=sum(z[k] for z in families) if mode=="compact-reuse" or k=="selected" else 0
                samples.append(row)
            runs.extend(samples)
            r={**case_round,**paired(samples)};series.append(r);pairs.append(r)
            by={(p["mode"],p["side"]):p for p in samples}
            for name in ("stock","off","compact-cold","compact-reuse"):
                p0=by[("compact" if name.startswith("compact-") else name,"P0")];p1=by[name,"P1"]
                cycles.append(dict(**case_round,mode=name,P0_ns=p0["wall_ns"],P1_ns=p1["wall_ns"],
                    cycle_ns=p0["wall_ns"]+p1["wall_ns"],P0_RSS_KiB=p0["peak_rss_KiB"],P1_RSS_KiB=p1["peak_rss_KiB"],
                    max_single_process_RSS_KiB=max(p0["peak_rss_KiB"],p1["peak_rss_KiB"])))
        ns=round(read(root/"manifest.json")["monotonic_resolution_s"]*1e9)
        summaries[c]=summarize_costs(series,ns)
        record_rss[c]={m:describe([v["peak_rss_KiB"] for v in runs if v["case"]==c and v["side"]=="P0" and v["mode"]==m])
                       for m in ("stock","off","light-quality","light-no-quality","compact")}
    gate=evaluate(summaries,funnel,rounds,dec["cases"])
    gate.update(rounds=rounds,primary_samples=sched["primary_samples"],observer_samples=sched["clock_only_samples"],
        trigger=dec["extend"],failed_samples=len(sched["failures"]),
        exact_false_admissions=sum(o["independent_false_admissions"] for v in provenance.values() for o in v.values()),
        changed_maps_vs_D=sum(not o["same_mu_as_D"] for v in provenance.values() for o in v.values()))
    for name,rows in (("runs.tsv",runs),("cycles.tsv",cycles),("funnel.tsv",funnel),("pairs.tsv",pairs)):
        write(out,name,rows)
    for name,obj in (("paired",summaries),("P0-rss",record_rss),("native-properties",checks),("production-libraries",stat),
                     ("actual-maps",provenance),("gate",gate)):
        save(out/(name+".json"),obj)
    print(json.dumps(gate,indent=2),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("formal","D_raw_restore","output"):
        p.add_argument(arg,type=Path)
    p.add_argument("--B-accepted",type=Path);p.add_argument("--D42",type=Path)
    a=p.parse_args()
    summarize(a.formal,a.D_raw_restore,a.B_accepted,a.D42,a.output)
