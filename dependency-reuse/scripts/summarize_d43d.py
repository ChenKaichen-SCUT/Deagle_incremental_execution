"""Compose D-stage measured work, independent qualification and per-birth native hit receipts."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
from cases42 import load
from d43_project_support import check,digest,save


def read(p):
    return json.loads(p.read_bytes())


def table(path):
    with path.open() as f:
        yield from csv.DictReader(f,delimiter="\t")


def write(out,name,rows):
    keys=list(dict.fromkeys(k for row in rows for k in row))
    with (out/name).open("w",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=keys,delimiter="\t",lineterminator="\n")
        writer.writeheader();writer.writerows(rows)


def keyed(p):
    return {key:int(value) if key!="stop" else value for key,value in (l.split() for l in p.read_text().splitlines())}


def phase(case,mode,side,folder,companion):
    meta=read(folder/"run.json");result=read(folder/"result.json");native=folder/"native"
    counts=dict(result["queries"][-1]["native_cumulative"] or {})
    wall=meta["wall_ns"]+meta.get("setup_ns",0)+meta.get("seal_ns",0)
    model=folder
    if mode=="stock":
        model=companion/side;stamp=model/"work/stock-root-clock";search=model/"work/stock-search.tsv"
    else:
        stamp=native/"search.tsv.root-clock";search=native/"search.tsv"
    root=int(stamp.read_text().splitlines()[0])-read(model/"run.json")["monotonic_start_ns"]
    search_ns=sum(int(l.split()[0]) for l in search.read_text().splitlines())
    row=dict(case=case,mode=mode,side=side,wall_ns=wall,process_ns=meta["wall_ns"],setup_ns=meta.get("setup_ns",0),
             P0_seal_ns=meta.get("seal_ns",0),model_to_root_ns=root,search_ns=search_ns,peak_rss_KiB=meta["peak_rss_kib"],
             phase_clock="stock_clock_observer" if mode=="stock" else "same_native_run",
             classification=result["classification"],target=result["target_status"])
    if (native/"import-time.tsv").is_file():
        imp=keyed(native/"import-time.tsv");row.update(imp)
        check(imp["P1_proof_recorder"]==imp["P1_dense_recorder"]==0,"P1 recorder active")
        last=list(map(int,(native/"cumulative-work.tsv").read_text().splitlines()[-1].split()))
        for k,n in zip(("sat_conflicts","decisions","sat_propagations","theory_propagations","theory_cycle_conflicts"),last):
            check(k not in counts or counts[k]==n,"native inclusive counters differ");counts[k]=n
        d=read(native/"compact-delta.json")["time_ns"];st=keyed(native/"structure-stats.tsv")
        row.update(archive_read_and_validation_ns=d["archive_read_validate"]+d["archive_payload_semantics"],
            semantic_variables_models_ns=d["semantic_variables_and_static_models"],theory_binding_ns=d["theory_bindings"],
            static_CNF_load_ns=st["static_CNF_read_ns"],structural_refinement_ns=st["refinement_ns"],
            map_write_ns=st["map_write_ns"],UsedLeaf_boolean_membership_ns=st["membership_ns"],dirty_build_ns=d["dirty"],
            label_filter_ns=d["label_filter"],native_read_and_import_ns=imp["native_batch_read_ns"]+imp["import_ns"])
        subtotal=sum(row[k] for k in ("archive_read_and_validation_ns","semantic_variables_models_ns","theory_binding_ns",
            "static_CNF_load_ns","structural_refinement_ns","map_write_ns","UsedLeaf_boolean_membership_ns","dirty_build_ns","label_filter_ns"))
        row["worker_other_ns"]=imp["worker_process_ns"]-subtotal
        check(row["worker_other_ns"]>=0,"overlapping preparation clocks")
        counts["inclusive_conflicts"]=counts["sat_conflicts"]+imp["root_conflicts"]-imp["root_conflicts_counter_delta"]
    else:counts["inclusive_conflicts"]=counts.get("sat_conflicts",0)
    row.update(counts);return row


def summarize(matrix,audits,tests,focus,out):
    out.mkdir(parents=True,exist_ok=False)
    runs=[];cycles=[];funnel=[];loss=[];mu=[];hits=[];checks={};results={}
    focus_results=read(focus/"controls.json")
    check({r["case"] for r in focus_results}==set(load()) and all(r["previous_mu_sha256"]==r["rerun_old_focus_mu_sha256"]
          and r["forbidden_structural_endpoints"]==0 for r in focus_results),"old-focus or interface control")
    stats_by_case={};names=("watch_unit","watch_conflict","analyze","minimize")
    for case in load():
        d=matrix/case;checks[case]=read(d/"checks.json")
        audit=read(audits/case/"audit.json");results[case]=audit
        stats=keyed(d/"compact/P0/native/dense.bin.stats");stats_by_case[case]=stats
        check(all(stats[k]==0 for k in ("SupportStore_instances","proof_nodes","proof_parent_edges","duplicate_condition_nodes",
              "legacy_recorders","legacy_quality_enabled")),"production allocated a proof graph")
        phases={}
        for mode in ("stock","off","compact-cold","compact-reuse"):
            for side in ("P0","P1"):
                label="compact" if mode.startswith("compact") and side=="P0" else mode
                if (label,side) not in phases:
                    row=phase(case,label,side,d/label/side,d/"stock-clock")
                    phases[label,side]=row;runs.append(row)
            p0=phases["compact" if mode.startswith("compact") else mode,"P0"]
            p1=phases[mode,"P1"]
            cycles.append(dict(case=case,mode=mode,P0_total_ns=p0["wall_ns"],P1_total_ns=p1["wall_ns"],
                 two_versions_ns=p0["wall_ns"]+p1["wall_ns"],maximum_single_process_RSS_KiB=max(p0["peak_rss_KiB"],p1["peak_rss_KiB"])))
        prod=d/"compact-reuse/P1/native";cold=d/"compact-cold/P1/native";policy=read(prod/"policy.json")
        seal=digest(d/"compact/P0/native/library.json")
        for n in (prod,cold):
            check(read(n/"control43.json")["library_sha256"]==read(n/"compact-delta.json")["producer"]==seal,"different P0 producers")
        for fn in ("effective-map.tsv","ready.tsv","eligible.tsv","input-matches.tsv","theory-matches.tsv","births.tsv"):
            check(digest(cold/fn)==digest(prod/fn),"cold/reuse preparation changed")
        check(audit["false_admissions"]==0 and audit["independent_replay_equal"],"exact audit gate failed")
        logs=list(table(prod/"imports.tsv"));first={}
        for w in table(prod/"hits.tsv"):
            key=int(w["id"]),names[int(w["use"])]
            check(key not in first,"duplicate first-use receipt");first[key]=w
        for fam in ("B","M","T","scope_only"):
            raw=policy["classes"][fam];qa=audit["classes"].get(fam,{})
            rows=[r for r in logs if r["family"]==fam]
            distinct=[r for r in rows if any(int(r[n]) for n in names)]
            classes=Counter(r["disposition"] for r in rows)
            record=dict(case=case,family=fam,born=raw.get("births",0),query=raw.get("query",0),unknown=raw.get("unknown",0),
                permanent=raw.get("permanent",0),translated=raw.get("mapped",0),exact=qa.get("exact",0),
                tags_passed=raw.get("eligible",0),selected=raw.get("chosen",0),attached=classes["attached"],
                root_unit=classes["root_unit"],root_conflict=classes["root_conflict"],root_satisfied=classes["root_satisfied"],
                duplicate_resident=classes["duplicate_resident"],duplicate_batch=classes["duplicate_batch"],
                tautology=classes["tautology"],already_inconsistent=classes["already_inconsistent"],distinct_hits=len(distinct))
            for n in names:record[n]=sum(int(r[n]) for r in rows)
            check(record["selected"]==len(rows) and record["tags_passed"]==qa.get("compact",0) and
                  record["distinct_hits"]==qa.get("hit",0),"native funnel disagrees with independent check")
            funnel.append(record)
            if fam!="scope_only":
                loss.append(dict(case=case,family=fam,**{k:qa.get(k,0) for k in ("permanent","unmapped_conclusion",
                    "mapped","mapped_but_exact_dead","exact","same_group_loss","logical_Uaudit","extra_UsedLeaf_loss",
                    "logical_Uactual","overflow_loss","compact")}))
            for r in distinct:
                item=dict(case=case,ordinal=r["id"],family=fam,translated=r["translated"],installed=r["installed"],
                          disposition=r["disposition"],first_cref=r["first_cref"],current_cref=r["current_cref"],moves=r["moves"])
                for n in names:
                    item[n]=int(r[n]);w=first.get((int(r["id"]),n))
                    check(bool(w)==bool(item[n]),"missing typed first-use witness")
                    item[n+"_first"]=json.dumps(w,separators=(",",":")) if w else ""
                hits.append(item)
        ch=audit["changed_images"]
        mu.append(dict(case=case,previous_mapped=audit["mapped_old"],actual_mapped=audit["mapped_current"],
            added=ch.get("added",0),lost=ch.get("lost",0),reassigned=ch.get("different_signed_peer",0),
            previous_exact=audit["previous_exact"],actual_exact=audit["actual_exact"],exact_gained=len(audit["exact_gained"]),
            exact_lost=len(audit["exact_lost"]),previous_compact=audit["previous_compact"],actual_compact=audit["actual_compact"],
            compact_gained=len(audit["compact_gained"]),compact_lost=len(audit["compact_lost"])))
    for name,rows in (("runs.tsv",runs),("cycles.tsv",cycles),("funnel.tsv",funnel),("losses.tsv",loss),
                      ("mapping.tsv",mu),("used-clauses.tsv",hits)):
        write(out,name,rows)
    repaired={r["case"] for r in funnel if r["family"]=="M" and r["attached"] and r["distinct_hits"] and r["case"]!="fib-snapshot-11"}
    reject=read(tests/"invalid/rejections.json");coverage=read(tests/"overflow/results.json")
    access=read(tests/"traced/access.json")
    root_control=(tests/"native/root-lifetime.txt").read_text()
    check("root_import\t1\tBCP\t2\ttheory\t1\troot_conflicts\t1\tnative_conflict_delta\t0" in root_control
          and "relocated rows" in (tests/"native/imports.txt").read_text(),"missing native root/GC controls")
    check(len(reject)==18 and all(not r["published"] for r in reject.values()) and coverage["complete"]["selected"]==512
          and coverage["unseen-B"]["eligible"]==coverage["unseen-T"]["eligible"]==0,"fail-closed controls")
    check(access["archived_proof_reads"]==access["old_mapping_reads"]==0,"old proof or recorded map was read")
    for p in ("P0","P1"):
        r=read(matrix/"fib-snapshot-11/stock"/p/"result.json")
        check(r["classification"]=="INCOMPLETE_UNWINDING" and r["unwinding_property_ids"],"lost historical unwind contract")
    totals={k:sum(r[k] for r in funnel) for k in ("born","permanent","translated","exact","tags_passed","selected","attached","distinct_hits")}
    totals["mixed_attached"]=sum(r["attached"] for r in funnel if r["family"]=="M")
    totals["mixed_hits"]=sum(r["distinct_hits"] for r in funnel if r["family"]=="M")
    save(out/"gate.json",dict(status="MIXED_REUSE_CONFIRMED" if repaired else "NO_REPAIR_MIXED_HIT",repair_cases=sorted(repaired),
         totals=totals,independent_false_admissions=sum(r["false_admissions"] for r in results.values()),
         fail_closed_checks=len(reject),overflow=coverage,observed_production_files=access["P0_library_files"],
         dynamic_proof_nodes=0,parent_edges=0,duplicate_theory_condition_DAGs=0,per_candidate_reproofs=0,
         actual_stock_ELF=read(matrix/"fib_updates_8/stock/P1/run.json")["binary_sha256"],formal_performance_rounds=0))
    save(out/"focus-controls.json",focus_results)
    save(out/"native-properties.json",checks);save(out/"independent.json",results);save(out/"P0-recorders.json",stats_by_case)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("matrix","audits","tests","focus","output"):p.add_argument(k,type=Path)
    a=p.parse_args();summarize(a.matrix,a.audits,a.tests,a.focus,a.output)
