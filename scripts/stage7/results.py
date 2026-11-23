"""Derive paired measurements and case-level denominators from the recorded services."""
import re
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

from incdeagle.model.identity import digest, file_sha, read
from incdeagle.model.observe import EVENTS
from incdeagle.model.repeat import phase_digest

ROOT=Path(__file__).resolve().parents[2]
PHASES=("goto","raw_ssa","sc_input","full_model")
BOUND="NO_VIOLATION_WITHIN_BOUND"
FAILURES=("UNKNOWN","TIMEOUT","OOM","ERROR","INCOMPLETE_UNWINDING")


def group_measure(folder,phase):
    record=read(folder/"measurement.json")
    marks=record["times"]
    a,b=marks.get(phase+"_start"),marks.get(phase+"_end")
    service=read(folder/"service.json")
    if not a or not b:
        return {"wall":None,"cpu":None,"rss_kib":None,"cgroup_kib":None,"samples":None,
                "max_waited_child_rss_kib":record.get("max_waited_child_rss_kib")}
    lo,hi=a["monotonic_ns"],b["monotonic_ns"]
    if not service["launch_ns"]<=lo<hi<=service["finish_ns"]:raise ValueError("Invalid service clock")
    points=[p for p in service["samples"] if lo<=p[0]<=hi]
    return {"wall":(hi-lo)/1e9,"cpu":(b["cpu_usage_us"]-a["cpu_usage_us"])/1e6,
            "cpu_user":(b["user_us"]-a["user_us"])/1e6,"cpu_system":(b["system_us"]-a["system_us"])/1e6,
            "rss_kib":max((p[1] for p in points),default=None),"cgroup_kib":max((p[2] for p in points),default=None),
            "samples":len(points),"max_waited_child_rss_kib":record.get("max_waited_child_rss_kib")}


def runtime_messages(path):
    if not path.is_file():return {}
    timings={}
    for row in read(path):
        m=re.fullmatch(r"Runtime (.+?):\s*([0-9.eE+-]+)s",row.get("messageText",""))
        if m:timings[m[1]]=float(m[2])
    return timings


def source_cost(name):
    if name=="batch_total":
        row=read(ROOT/"reports/evidence/stage-06/cases/ai-single-edit.json")
        return {"seconds":row["repair_elapsed_ns"]/1e9,"scope":"successful Stage 6 AI adapter and freeze",
                "source":"reports/evidence/stage-06/cases/ai-single-edit.json"}
    if name=="split_counter":
        log=next((ROOT/"reports/evidence/stage-02").glob("mini-*.json"))
        m=read(log)
        duration=datetime.fromisoformat(m["finished_utc"])-datetime.fromisoformat(m["started_utc"])
        return {"seconds":duration.total_seconds(),"scope":"Stage 2 mini controller span",
                "source":log.relative_to(ROOT).as_posix()}
    return {"seconds":None,"scope":"original manual authoring duration unavailable","source":None}


def sec(value):
    return None if value is None else value/1e9


def cycle(*parts):
    if any(part is None for part in parts):
        return None
    # The recorded wall clocks have nanosecond resolution. Add integer ticks so
    # the same evidence produces identical JSON across Python versions.
    return sum(round(part * 1_000_000_000) for part in parts) / 1_000_000_000


def diagnose(case, folder):
    w=read(folder/"workflow.json")
    info={"status":w["status"],"model_match":w.get("model_match"),"agreement":w.get("agreement"),
          "old_result":(w.get("old") or {}).get("classification"),"candidate":(w.get("online") or {}).get("classification"),
          "incremental_trace_steps":w.get("candidate_trace_steps"),"full_diagnostic_time":None,"extra_diagnostic_and_compare_time":None,
          "phases":None,"structure":None,"full_dispatches":None,"events":None,"rf_constraints":None}
    path=folder/"model-check.json"
    if not path.is_file():return info
    m=read(path)
    info["full_diagnostic_time"]=read(folder/"full-model/verification.json")["wall_ns"]/1e9
    import json
    ev={x["event"]:x["monotonic_ns"] for x in map(json.loads,(folder/"events.jsonl").read_bytes().splitlines())}
    info["extra_diagnostic_and_compare_time"]=(ev["model_diagnostic_finished"]-ev["model_diagnostic_started"])/1e9
    if not all(phase_digest(read(folder/where/(p+".json")))==m["phase_digests"][p][role]
               for p in PHASES for role,where in (("full","full-model"),("online","pair/candidate"))):
        raise ValueError("Diagnostic phase inconsistency: "+case)
    if not m["match"] or not m["dispatch_accounting"] or m["model_digests"]["online"]!=m["model_digests"]["full"]:
        raise ValueError("Model mismatch: "+case)
    info.update(phases={p:m["phase_digests"][p]["full"] for p in PHASES},structure=m["model_digests"]["full"],
                full_dispatches=len(read(folder/"full-model/visits.json")))
    full=read(folder/"full-model/full_model.json")
    raw=read(folder/"full-model/raw_ssa.json")
    info["events"]=sum(s["kind"] in EVENTS for s in raw["steps"])
    info["rf_constraints"]=sum(s["kind"]=="constraint" and s.get("comment") in ("rf-val","rf-some") for s in full["steps"])
    return info


def row_for(root,item,trial,diag):
    t=read(trial/"trial.json")
    inc=read(trial/"incremental/measurement.json")
    full=read(trial/"full/measurement.json")
    old=read(trial/"old_full/measurement.json")
    resources={p:group_measure(trial/("incremental" if p=="old_instrumented" else p),p)
               for p in ("old_full","old_instrumented","full","incremental")}
    resources["incremental_session_max_sampled_rss_kib"]=max((r for r in
        (resources[p]["rss_kib"] for p in ("old_instrumented","incremental")) if r is not None),default=None)
    times={p:resources[p]["wall"] for p in ("old_full","old_instrumented","full","incremental")}
    candidate=trial/"incremental/pair/candidate"
    metrics=read(candidate/"metrics.json")["phase_nanoseconds"] if (candidate/"metrics.json").exists() else {}
    elapsed=runtime_messages(trial/"full/verify/result.json")
    stats=inc.get("native",{})
    sc=stats.get("sc_counters",{})
    theory=inc.get("theory",{})
    finished=inc["status"]=="COMPLETED"
    skipped=stats.get("reused_prefix_symex_steps")
    reused=stats.get("checkpoint_raw_events",0) if finished and stats.get("checkpoint_used") else (0 if finished else None)
    retained=sc.get("coverage_formulas_reused",0)+sc.get("value_formulas_reused",0) if finished else None
    old_hash=item["files"]["old/program.c"]
    p1=item["files"]["candidate/program.c"]
    for run,expected in ((inc,p1),(full,p1),(old,old_hash)):
        if run["status"]=="COMPLETED" and run["inputs"]!={"program.c":expected,"harness.c":item["files"]["harness.c"]}:
            raise ValueError("Inconsistent verifier inputs")
    common=t["verified_replay_patch_seconds"]
    history=source_cost(item["case_id"])
    fixed=root/"fixed-traces"/(item["case_id"]+".json")
    unit=[old_hash,file_sha(fixed),p1,item["files"]["phi.json"],item["files"]["gamma.json"]]
    result={"case_id":item["case_id"],"repeat":t["repeat"],"order":t["order"],
        "patch_origin":item["patch_origin"],"patch_type":item["patch_type"],"old_hash":old_hash,"new_hash":p1,
        "config_hash":item["files"]["gamma.json"],"property_hash":item["files"]["phi.json"],
        "reference_cex0_sha256":unit[1],"experiment_unit_sha256":digest(unit),
        "old_result":old.get("verdict",{}).get("classification",old["status"]),
        "old_instrumented_result":inc.get("old_verdict",{}).get("classification"),"old_cex":inc.get("old_trace"),
        "full_result":full.get("verdict",{}).get("classification",full["status"]),
        "incremental_result":inc.get("verdict",{}).get("classification",inc["status"]),
        "full_cex":full.get("trace"),"incremental_cex":inc.get("trace"),"agreement_status":t["agreement"],
        "full_time":times["full"],"incremental_time":times["incremental"],"old_full_time":times["old_full"],
        "old_instrumented_time":times["old_instrumented"],"replay_patch_time":common,
        "full_replay_cycle_time":cycle(times["old_full"],common,times["full"]),
        "incremental_replay_cycle_time":cycle(times["old_instrumented"],common,times["incremental"]),
        "historical_repair":history,"full_cycle_with_measured_repair":cycle(times["old_full"],history["seconds"],times["full"]),
        "incremental_cycle_with_measured_repair":cycle(times["old_instrumented"],history["seconds"],times["incremental"]),
        "parse_time":{"full":None,"incremental_frontend_wall":inc.get("frontend_seconds")},
        "symex_time":{"full":elapsed.get("Symex"),"incremental":sec(metrics.get("symbolic_execution"))},
        "event_model_time":{"full":None,"incremental":sec(metrics.get("event_constraints"))},
        "cnf_time":{"full_convert_ssa":elapsed.get("Convert SSA"),"incremental_cnf_and_graph":sec(metrics.get("cnf_and_graph"))},
        "solve_time":{"full":elapsed.get("Solver"),"incremental":sec(metrics.get("solve"))},
        "change_analysis_time":inc.get("change_analysis_seconds"),"checkpoint_restore_time":None,
        "constraint_update_time":sec(metrics.get("event_constraints")),"lemma_validate_time":sec(theory.get("audit_ns")),
        "lemma_bind_time":sec(theory.get("binding_ns")),"lemma_import_time":sec(theory.get("import_ns")),"cache_io_time":None,
        "full_symex_steps":diag["full_dispatches"],"executed_new_symex_steps":stats.get("executed_symex_steps"),
        "reused_prefix_steps":skipped,"events_reused":reused,
        "events_rebuilt":diag["events"]-reused if reused is not None and diag["events"] is not None else None,
        "constraints_retained":retained,"constraints_rebuilt":diag["rf_constraints"]-retained if retained is not None and diag["rf_constraints"] is not None else None,
        "read_bundles_reused":sc.get("read_bundles_reused",0) if finished else None,
        "po_edges_reused":sc.get("thread_edges_reused",0) if finished else None,
        "lemmas_exported":theory.get("exported"),"lemmas_imported":theory.get("imported"),"lemmas_rejected":theory.get("rejected"),
        "model_path":inc.get("path"),"fallback_reason":inc.get("fallback_reason"),"theory_context_differences":theory.get("context_differences"),
        "peak_rss":{p:resources[p]["rss_kib"] for p in times},"resources":resources,
        "api_calls":0,"input_tokens":0,"output_tokens":0,"estimated_api_cost":0,
        "speedup":times["full"]/times["incremental"] if t["agreement"]=="DEFINITE_AGREEMENT" and all((times["full"],times["incremental"])) else None,
        "full_native_messages_seconds":elapsed,"incremental_native_phases_ns":metrics,"formal_phase_match":None}
    if finished and diag["phases"]:
        hashes={p:phase_digest(read(candidate/(p+".json"))) for p in PHASES}
        result["formal_phase_match"]=hashes==diag["phases"]
        if not result["formal_phase_match"] or result["full_symex_steps"]!=skipped+stats["executed_symex_steps"]:
            raise ValueError("Formal candidate differs from the diagnostic in "+str(trial))
        if min(result["events_rebuilt"],result["constraints_rebuilt"])<0:
            raise ValueError("Native retained count exceeds the complete diagnostic")
    return result


def median(rows,key):
    values=[r[key] for r in rows if r.get(key) is not None]
    return statistics.median(values) if values else None


def derive(root):
    plan=read(root/"plan.json")
    matrix=read(root/"matrix.json")
    diags={name:diagnose(name,root/"diagnostics"/name) for name in plan["cases"]}
    rows=[row_for(root,matrix[s["case_id"]],root/"trials"/s["case_id"]/str(s["repeat"]),diags[s["case_id"]]) for s in plan["schedule"]]
    cases={}
    for name in plan["cases"]:
        subset=[r for r in rows if r["case_id"]==name]
        agreed=[r for r in subset if r["agreement_status"]=="DEFINITE_AGREEMENT"]
        first=subset[0]
        c={k:first[k] for k in ("patch_origin","patch_type","full_result","incremental_result","old_result","model_path","fallback_reason",
            "full_symex_steps","executed_new_symex_steps","reused_prefix_steps","events_reused","constraints_retained",
            "lemmas_exported","lemmas_imported","lemmas_rejected","theory_context_differences")}
        c.update(runs=len(subset),definite_agreement=len(agreed),formal_phase_matches=sum(r["formal_phase_match"] is True for r in subset),
                 speedups=[r["speedup"] for r in subset],result_counts=dict(Counter(r["incremental_result"] for r in subset)),
                 agreement_counts=dict(Counter(r["agreement_status"] for r in subset)))
        c["medians"]={k:median(subset,k) for k in ("speedup","full_time","incremental_time","old_full_time","old_instrumented_time",
                     "full_replay_cycle_time","incremental_replay_cycle_time","full_cycle_with_measured_repair",
                     "incremental_cycle_with_measured_repair","change_analysis_time","lemma_validate_time")}
        c["rss_median_kib"]={p:median([r["peak_rss"] for r in subset],p) for p in first["peak_rss"]}
        cases[name]=c
    speed=[s["medians"]["speedup"] for s in cases.values() if s["medians"]["speedup"] is not None]
    hits=[s["medians"]["speedup"] for s in cases.values() if s["medians"]["speedup"] is not None and (s["reused_prefix_steps"] or 0)>0]
    totals={"distinct_pairs":len(cases),"trials":len(rows),"model_diagnostics_passed":sum(d["model_match"] is True for d in diags.values()),
            "formal_phase_matches":sum(r["formal_phase_match"] is True for r in rows),
            "agreement_counts":dict(Counter(r["agreement_status"] for r in rows)),
            "pairs_all_definite_agree":sum(c["definite_agreement"]==c["runs"] for c in cases.values()),
            "pairs_bounded_pass":sum(c["result_counts"]=={BOUND:c["runs"]} and c["definite_agreement"]==c["runs"] for c in cases.values()),
            "pairs_remaining_violation":sum(c["result_counts"]=={"VIOLATION":c["runs"]} and c["definite_agreement"]==c["runs"] for c in cases.values()),
            "pairs_prefix_reused":sum((s["reused_prefix_steps"] or 0)>0 for s in cases.values()),
            "pairs_model_fallback":sum(s["model_path"]=="full_fallback" for s in cases.values()),
            "pairs_real_import":sum((s["lemmas_imported"] or 0)>0 for s in cases.values()),
            "pairs_all_lemmas_rejected":sum((s["lemmas_exported"] or 0)>0 and s["lemmas_rejected"]==s["lemmas_exported"] for s in cases.values()),
            "resource_and_unknown":{p:{k:sum(r[p]==k for r in rows) for k in FAILURES} for p in ("full_result","incremental_result")},
            "full_over_incremental_median":statistics.median(speed) if speed else None,
            "full_over_incremental_geomean":statistics.geometric_mean(speed) if speed else None,
            "hit_subset_median":statistics.median(hits) if hits else None,"hit_pairs_with_speedup":len(hits),
            "pairs_with_speedup":len(speed),"pairs_faster":sum(x>1 for x in speed),"api_calls":0}
    return rows,{"totals":totals,"cases":cases,"diagnostics":diags}
