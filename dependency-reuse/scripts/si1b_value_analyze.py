"""Recompute the P1-only value ledger, check real native use and calculate paired work/time budgets."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import median

from audit_d43d import batches
from run_d42 import compare
from si1b_review_space import BASE, EVIDENCE, check, digest, read, rows, save, table
from si1b_value_boundary import batch_bytes, model_certificate
from summarize_d43d import keyed, write
from summarize_stock import interpret

HITS=("watch_unit","watch_conflict","analyze","minimize")
WORK=("sat_conflicts","decisions","sat_propagations","theory_propagations","theory_cycle_conflicts")
DIFFERENCES=("read_import_search_ns","import_search_ns","search_ns","native_import_ns","batch_read_ns","diagnostic_prep_ns",
             "process_ns","full_validation_ns","with_fixture_to_exit_ns","model_to_root_ns","rss_KiB","restarts","inclusive_conflicts",
             "decisions","sat_propagations","theory_propagations","theory_cycle_conflicts","dynamic_co_batches_added","dynamic_co_pairs_added",
             "root_propagations","root_conflicts","attached","distinct_hits",*HITS)


def certified(case):
    lib=EVIDENCE/"si1b-value/frozen"/case
    lock=read(lib.parent/"batches.json")["seals"][case]
    check(digest(lib/"seal.json")==lock,"untrusted seal")
    seal=read(lib/"seal.json"); pools={}
    for arm in ("A","new"):
        config=seal["batches"][arm]
        batch_bytes(lib/(arm+".ready.tsv"),seal["model"]["nvars"],config)
        xs=batches(lib/(arm+".ready.tsv"),True)
        logical=list(rows(lib/(arm+".pool.tsv.gz")))
        oracle={int(r["ordinal"]):(r["family"],list(map(int,r["translated_literals"].split()))) for r in logical}
        check(len(oracle)==len(logical)==config["eligible"] and list(oracle)==sorted(oracle)
              and list(xs.items())==list(oracle.items())[:512],"invalid first512")
        pools[arm]=xs
    overlap=pools["A"].keys()&pools["new"].keys()
    check(sorted(overlap)==seal["selected_birth_intersection"] and all(pools["A"][i]==pools["new"][i] for i in overlap),
          "intersection changed")
    return seal,pools


def clocks(path,root_conflict):
    if not path.exists():
        check(root_conflict,"missing search clock without an import root conflict")
        return 0,0,[]
    values=[list(map(int,x.split())) for x in path.read_text().splitlines()]
    check(values or root_conflict,"empty search log")
    check(all(len(x)==2 and min(x)>=0 for x in values),"bad search clock")
    return sum(x[0] for x in values),sum(max(0,x[1]-1) for x in values),values


def uses(sample,folder,seal,pools,by_family,by_membership,witnesses,all_rows):
    native=folder/"native";arm=sample["arm"]
    label="A" if arm=="A" else "new"
    pool=pools[label];shared=pools["A"].keys()&pools["new"].keys()
    selected=seal["batches"][label]
    receipt=read(native/"diagnostic-receipt.json")
    meta=read(folder/"run.json")
    check(model_certificate(native/"boundary.tsv",Path(meta["cwd"]))==seal["model"]==receipt["canonical_model"] and
          receipt["actual_inputs"]==meta["input_sha256"]==seal["inputs"] and receipt["arm"]==arm and
          receipt["seal_sha256"]==read(EVIDENCE/"si1b-value/frozen/batches.json")["seals"][sample["case"]] and
          receipt["checked_elf"]==meta["binary_sha256"]==seal["native_elf"] and
          digest(native/"ready.tsv")==selected["sha256"]==receipt["checked_batches"][label],"live model/batch receipt")
    fr=list(rows(native/"hits.tsv"))
    first={(int(r["id"]),HITS[int(r["use"])]):r for r in fr}
    check(len(first)==len(fr),"duplicate first use")
    native_rows=list(rows(native/"imports.tsv"))
    check([int(r["id"]) for r in native_rows]==list(pool),"native import order")
    groups=defaultdict(Counter)
    actual=Counter()
    for row in native_rows:
        i=int(row["id"]);fam=row["family"]; disposition=row["disposition"]
        c=list(map(int,row["translated"].split()))
        installed=list(map(int,row["installed"].split()))
        check((fam,c)==pool[i] and set(installed)<=set(c),"unexpected column/literal in native attachment")
        if arm=="cold":check(disposition=="check_only","cold attached")
        else:check(disposition in {"attached","root_unit","root_conflict","root_satisfied","already_inconsistent",
                                   "tautology","duplicate_batch","duplicate_resident"},"unknown native disposition")
        hitvals={k:int(row[k]) for k in HITS}
        touched=bool(any(hitvals.values()))
        check(not touched or disposition=="attached","hit on unattached row")
        cohort="shared" if i in shared else ("A_only" if label=="A" else "new_only")
        for k,n in hitvals.items():
            event=first.pop((i,k),None)
            check(bool(event)==bool(n),"missing typed first use")
            if event:
                check(sorted(map(int,event["clause"].split()))==sorted(installed) and
                      int(event["level"])>=0 and int(event["conflict_counter"])>=0,"wrong first-use clause")
                witnesses([sample["case"],sample["round"],arm,i,fam,cohort,k,n,event["cref"],event["level"],
                           event["raw_literal"],event["conflict_counter"],event["clause"]])
        counters=dict(attached=int(disposition=="attached"),distinct_hits=int(touched),
                      root_unit=int(disposition=="root_unit"),direct_root_conflict=int(disposition=="root_conflict"),
                      selected=int(arm!="cold"),read_rows=1,**hitvals)
        for bucket in (actual,groups[("family",fam)],groups[("membership",cohort)]):bucket.update(counters)
        all_rows([sample["case"],sample["round"],arm,i,fam,cohort,disposition,row["translated"],row["installed"],
                  row["root_witness"],row["root_false"],row["first_cref"],row["current_cref"],row["moves"],*hitvals.values()])
    check(not first,"spurious first use")
    for label,table_out,names in (("family",by_family,("B","M","T")),("membership",by_membership,("shared","new_only","A_only"))):
        for value in names:
            bucket=groups[label,value]
            table_out.append(dict(case=sample["case"],round=sample["round"],arm=arm,group=value,
                                  **{k:bucket[k] for k in ("selected","read_rows","attached","distinct_hits","root_unit","direct_root_conflict",*HITS)}))
    return dict(actual)


def audit_case_round(case,n,root,dref,settings,seal,pools,all_rows,witnesses,families,cohorts):
    base=root/case/str(n)
    gold=base/"stock";companion=base/"stock-clock"
    checks={"stock_vs_frozen":compare(dref/"matrix"/case/"stock/P1",gold,True),"stock_clock_vs_stock":compare(gold,companion,True)}
    samples={}
    for arm in ("stock","cold","A","new"):
        folder=base/arm;meta=read(folder/"run.json");outcome=read(folder/"outcome.json")
        r,_=interpret(meta,(folder/"stdout").read_text())
        check(r==read(folder/"result.json") and not meta["timed_out"] and meta["exit_code"]==0 and meta["cpu_affinity"]==[0] and
              meta["limits"]==seal["limits"] and meta["input_sha256"]==seal["inputs"] and
              all(digest(folder/"work"/name)==h for name,h in seal["inputs"].items()) and
              digest(folder/"stdout")==meta["stdout_sha256"] and digest(folder/"stderr")==meta["stderr_sha256"],"run record")
        expected_class="INCOMPLETE_UNWINDING" if case=="fib-snapshot-11" else "BOUNDED_PASS"
        check(r["classification"]==expected_class and r["target_status"]=="SUCCESS" and
              len(r["unwinding_property_ids"])==(3 if case=="fib-snapshot-11" else 0),"classification changed")
        static=0; imp={};imp_ns=read_ns=worker_ns=0
        counts=Counter(r["queries"][-1]["native_cumulative"] or {})
        phase={"case":case,"round":n,"arm":arm}
        if arm=="stock":
            check(meta["binary_sha256"]==settings["binary_sha256"]["stock"],"not pristine stock")
            clock_dir=companion/"work";clock=clock_dir/"stock-search.tsv"
            stamp=clock_dir/"stock-root-clock";clock_meta=read(companion/"run.json")
            check(clock_meta["binary_sha256"]==settings["binary_sha256"]["stock-clock"] and clock_meta["cpu_affinity"]==[0]
                  and clock_meta["limits"]==meta["limits"] and clock_meta["input_sha256"]==meta["input_sha256"],"stock observer")
            counts["inclusive_conflicts"]=counts["sat_conflicts"]
            use={k:0 for k in ("selected","read_rows","attached","distinct_hits","root_unit","direct_root_conflict",*HITS)}
            observation="separate_stock_clock"
        else:
            native=folder/"native";clock=native/"search.tsv";stamp=native/"search.tsv.root-clock";clock_meta=meta
            checks[arm+"_vs_stock"]=compare(gold,folder,arm=="cold")
            check(meta["binary_sha256"]==settings["binary_sha256"]["diagnostic"],"wrong diagnostic binary")
            imp=keyed(native/"import-time.tsv")
            check(imp["P1_proof_recorder"]==imp["P1_dense_recorder"]==0,"P1 recorder active")
            imp_ns,read_ns,worker_ns=imp["import_ns"],imp["native_batch_read_ns"],imp["worker_process_ns"]
            last=list(map(int,(native/"cumulative-work.tsv").read_text().splitlines()[-1].split()))
            check(len(last)==6 and last[5] in (0,1),"native cumulative work incomplete")
            for k,val in zip(WORK,last[:5]):
                check(k not in counts or counts[k]==val,"work differs from native totals")
                counts[k]=val
            check(0<=imp["root_conflicts_counter_delta"]<=imp["root_conflicts"]<=1,"inconsistent root conflict count")
            counts["inclusive_conflicts"]=counts["sat_conflicts"]+imp["root_conflicts"]-imp["root_conflicts_counter_delta"]
            use=uses(phase,folder,seal,pools,families,cohorts,witnesses,all_rows)
            label="A" if arm=="A" else "new"
            static=seal["batches"][label]["eligible"]
            observation="same_process"
        if arm=="stock":
            check(all(k in counts for k in WORK),"missing stock statistics")
        ns,restarts,logs=clocks(clock,imp.get("root_conflicts",0))
        if not logs:
            check(counts["decisions"]==0 and imp["root_conflicts"],"early return unexplained")
        root_ns=int(stamp.read_text().splitlines()[0])-clock_meta["monotonic_start_ns"]
        prep=worker_ns+outcome["setup_ns"]
        elapsed=meta["wall_ns"]+outcome["setup_ns"]
        row=dict(**phase,classification=r["classification"],target=r["target_status"],clock_source=observation,
                 logical_pool_checked=static,eligible_to_attach=static if arm in ("A","new") else 0,**use,
                 root_assignments_before=imp.get("root_before"),root_assignments_after=imp.get("root_after"),
                 root_propagations=imp.get("root_propagations_counter_delta",0),root_theory_propagations=imp.get("root_theory_propagations_counter_delta",0),
                 root_cycle_conflicts=imp.get("root_theory_cycles_counter_delta",0),root_decisions=imp.get("root_decisions_counter_delta",0),
                 root_conflicts=imp.get("root_conflicts",0),root_native_conflict_delta=imp.get("root_conflicts_counter_delta",0),
                 **{k:counts.get(k) for k in (*WORK,"dynamic_co_batches_added","dynamic_co_pairs_added","inclusive_conflicts")},
                 restarts=restarts,model_to_root_ns=root_ns,search_ns=ns,batch_read_ns=read_ns,native_import_ns=imp_ns,
                 import_search_ns=imp_ns+ns if arm!="stock" else None,read_import_search_ns=read_ns+imp_ns+ns if arm!="stock" else None,
                 worker_ns=worker_ns,setup_ns=outcome["setup_ns"],diagnostic_prep_ns=prep,process_ns=meta["wall_ns"],
                 full_validation_ns=elapsed,with_fixture_to_exit_ns=meta["monotonic_start_ns"]+meta["wall_ns"]-outcome["start_ns"],
                 rss_KiB=meta["peak_rss_kib"],exit_code=meta["exit_code"])
        # Stock clock comes from another process. Its readings are never subtracted from pristine wall.
        check(row["with_fixture_to_exit_ns"]>=elapsed and (arm=="stock" or meta["wall_ns"]>=worker_ns+imp_ns+read_ns+ns),"invalid time accounting")
        samples[arm]=row
    return samples,checks


def analyze(root,dref,out):
    out.mkdir(parents=True,exist_ok=False)
    plan=read(BASE/"configs/si1b-value.json")
    settings=read(root/"environment.json")
    check(settings["preregistered_plan_sha256"]==digest(BASE/"configs/si1b-value.json") and settings["cpu"]==[0], "wrong plan/cpu")
    primary=[(n,c,m) for n,order in enumerate(plan["round_orders"],1) for c in plan["cases"] for m in order]
    expected=primary+[(n,c,"stock-clock") for n in range(1,4) for c in plan["cases"]]
    schedule=[json.loads(x) for x in (root/"schedule.jsonl").read_text().splitlines()]
    starts=[json.loads(x) for x in (root/"starts.jsonl").read_text().splitlines()]
    check([(x["round"],x["case"],x["arm"]) for x in schedule]==expected and len(starts)==len(schedule),"unexpected sequence")
    last=0
    for row,start in zip(schedule,starts):
        check(row==read(root/row["case"]/str(row["round"])/row["arm"]/"outcome.json") and
              all(row[k]==v for k,v in start.items()) and row["ok"] and last<=row["start_ns"]<=row["end_ns"],"overlap or incomplete sample")
        last=row["end_ns"]
    samples=[];paired=[];checks={};families=[];cohorts=[];summary={}
    with table(out/"native-imports.tsv.gz","case round arm ordinal family membership disposition translated installed root_witness removed_false first_cref final_cref GC_moves watch_unit watch_conflict analyze minimize") as all_rows, \
         table(out/"first-uses.tsv.gz","case round arm ordinal family membership action total cref level raw_literal conflict_counter installed_at_hit") as witnesses:
        for case in plan["cases"]:
            seal,pools=certified(case);checks[case]={}
            for n in range(1,4):
                group,properties=audit_case_round(case,n,root,dref,settings,seal,pools,all_rows,witnesses,families,cohorts)
                samples.extend(group.values());checks[case][n]=properties
                for baseline in ("cold","A"):
                    left,rite=group[baseline],group["new"]
                    diff={k:(left[k]-rite[k] if left[k] is not None and rite[k] is not None else None) for k in DIFFERENCES}
                    gain=diff["read_import_search_ns"]/left["read_import_search_ns"]
                    paired.append(dict(case=case,round=n,baseline=baseline,primary_fraction_saved=gain,**diff,
                                       unspent_joint_cost_budget_ns=max(0,diff["read_import_search_ns"]),
                                       budget_to_keep_five_percent_ns=max(0,95*left["read_import_search_ns"]//100-rite["read_import_search_ns"]),
                                       signed_stock_full_minus_new_full_ns=group["stock"]["full_validation_ns"]-rite["full_validation_ns"]))
            comparison={}
            for mode in ("cold","A"):
                records=[x for x in paired if x["case"]==case and x["baseline"]==mode]
                xs=[x["primary_fraction_saved"] for x in records]
                net=median(x["read_import_search_ns"] for x in records)
                comparison[mode]=dict(paired_fractions=xs,median_fraction_saved=median(xs),positive_pairs=sum(v>0 for v in xs),
                    median_signed_budget_ns=net,median_affordable_additional_cost_ns=max(0,net),
                    median_raw_search_saving_ns=median(x["search_ns"] for x in records),
                    median_signed_full_wall_saving_ns=median(x["full_validation_ns"] for x in records),
                    threshold_met=median(xs)>=.05 and sum(v>0 for v in xs)>=2)
            medians={}
            for arm in ("stock","cold","A","new"):
                cohort=[x for x in samples if x["case"]==case and x["arm"]==arm]
                medians[arm]={k:median(x[k] for x in cohort) for k in cohort[0]
                              if all(type(x[k]) in (int,float) for x in cohort) and k!="round"}
            summary[case]=dict(per_arm_three_round_medians=medians,comparisons=comparison,both_thresholds=all(c["threshold_met"] for c in comparison.values()),
                repair_case=case=="fib_updates_8",median_stock_full_minus_new_full_ns=median(
                    x["signed_stock_full_minus_new_full_ns"] for x in paired if x["case"]==case and x["baseline"]=="cold"))
    write(out,"runs.tsv",samples);write(out,"paired-baseline-minus-new.tsv",paired)
    write(out,"family-use.tsv",families);write(out,"batch-membership-use.tsv",cohorts)
    save(out/"property-model-checks.json",dict(properties=checks,diagnostic_boundaries_verified=18,
         all_live_boundaries_equal_case_reference=True,both_case_batches_authenticated_per_diagnostic_run=True,
         primary=24,stock_clock_only=6,all_serial=True,native_P0_runs=0,exact_false_admissions=0))
    save(out/"summary.json",dict(stage="SI-1B-value",status="READY_FOR_REVIEW",cases=summary,
         real_repair_search_value_gate=summary["fib_updates_8"]["both_thresholds"],preregistered_threshold=.05,
         P0_runs=0,primary_P1_runs=24,stock_clock_companions=6,production_identity_registration=False))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for n in ("matrix","D","out"):p.add_argument(n,type=Path)
    a=p.parse_args();analyze(a.matrix,a.D,a.out)
