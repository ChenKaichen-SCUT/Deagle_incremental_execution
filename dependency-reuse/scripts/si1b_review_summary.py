"""Join exact birth evidence to group members and native port witnesses. No additional transport map is evaluated."""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path

from d43_project_support import check, digest
from si1b_review_space import CASES, EVIDENCE, MATRIX, jsonlines, read, rows, save, table


def analyze(case,droot,out):
    d=read(out/"results.json")
    expected=d["results"]
    mapping=[{},{}]
    for r in rows(droot/"matrix"/case/"compact-reuse/P1/native/effective-map.tsv"):
        if int(r["peer"])>=2:
            mapping[int(r["side"])][int(r["variable"])]=int(r["peer"])
    direct={int(r["old_variable"]):int(r["positive_image"]) for r in rows(EVIDENCE/"si1b"/case/"join/direct-map.tsv.gz")}
    added={int(r["old"]):(int(r["positive_image"]),int(r["typed_key"]),int(r["UsedLeaf"]))
           for r in rows(out/"added-witnesses.tsv.gz")}
    add_u={v for v,x in added.items() if x[2]}
    mu={"A":mapping[0],"B":direct,"C":mapping[0] | {v:x[0] for v,x in added.items()}}
    check(len(add_u)==d["used_atoms"]["C"]["union"]-d["used_atoms"]["A"]["union"],"added UsedLeaf denominator")
    # A group can regain a candidate even if that candidate's own proof was already alive under A.
    # Catalogue every formerly dirty member in each such cleaned slot, independent of the birth ledger.
    clean={k:[set(x)-set(y) for x,y in zip(d["dirty_slots"]["A"],d["dirty_slots"][k])] for k in ("B","C")}
    repairs={k:[defaultdict(list),defaultdict(list)] for k in clean}
    old=droot/"matrix"/case/"compact/P0/native/model.tsv"
    with old.open("rb") as stream:
        clauses=(l for l in stream if l.startswith(b"C\t"))
        n=0
        for row in rows(out/"boolean-leaves.tsv.gz"):
            seq=int(row["occurrence"]);slot=int(row["slot"])
            arms=[k for k in clean if slot in clean[k][0] and int(row["A_P1"])<=0]
            if not arms:continue
            while n<seq:
                line=next(clauses);n+=1
            ls=list(map(int,line.split()[2:]))
            for k in arms:
                peer=int(row[k+"_P1"])
                need={x//2 for x in ls if x>=2 and mu[k].get(x//2)!=mu["A"].get(x//2)}
                check(peer>0 and need and need<=add_u,"recovered slot lacks a certified UsedLeaf change")
                repairs[k][0][slot].append([seq,peer,[[v,*added[v][:2]] for v in sorted(need)]])
    for row in rows(out/"theory-leaves.tsv.gz"):
        fact=tuple(int(row[c]) for c in ("op","a","b","c"))
        for k in clean:
            slot=int(row["slot"])
            if row["actual_used"]=="1" and row["A"]!="M" and slot in clean[k][1]:
                check(row[k]=="M","theory group still dirty")
                repairs[k][1][slot].append([fact,row["A"],row[k]])
            if k=="C":
                check(row["A"]==row["C"],"ordinary extension changed a theory binding")
    with jsonlines(out/"slot-repairs.jsonl.gz") as append:
        for k in clean:
            for i,domain in enumerate(("B","T")):
                check(set(repairs[k][i])==clean[k][i],"missing repaired slot members")
                for slot,values in sorted(repairs[k][i].items()):
                    append(dict(map=k,domain=domain,slot=slot,all_formerly_unmatched_members=values))
    attr=defaultdict(Counter);union=set();per=Counter();both=Counter()
    with gzip.open(out/"gains.jsonl.gz","rt") as f, table(out/"gain-attribution.tsv.gz",
            "map ordinal Audit_id family exact_gain compact_gain newly_required_outside_UsedLeaf cleaned_B_slots cleaned_T_slots") as emit:
        for line in f:
            g=json.loads(line)
            k=g["map"];i=g["ordinal"];missing=g["new_bindings_on_conclusion_or_support"]
            union.add(i);per[k]+=1
            nonused=[]
            for v,prior,peer,key in missing:
                check(prior<0 and added[v][:2]==(peer,key),"birth key not in validated ordinary extensions")
                if v not in add_u:
                    check(v in {l//2 for l in g["formerly_untranslatable_conclusion"]},"outside UsedLeaf in base support")
                    nonused.append(v)
            slots=[]
            for di,domain in enumerate(("B","T")):
                oldslots={s for s,n,first in g["tagged_dirty_slots_with_counts_and_first_member"]["A"][domain]}
                newslots={s for s,n,first in g["tagged_dirty_slots_with_counts_and_first_member"][k][domain]}
                fixed=sorted(oldslots-newslots)
                check(set(fixed)<=repairs[k][di].keys(),"slot lacks witness")
                slots.append(fixed)
            if g["compact_gain"] and not g["exact_gain"]:
                check(any(slots),"compact-only gain without cleaned group")
                both[k+"_group_only"]+=1
            for metric in ("exact","compact"):
                if g[metric+"_gain"]:
                    label=k+"_"+metric
                    attr[label]["needs_outside_UsedLeaf_conclusion" if nonused else "UsedLeaf_additions_sufficient"]+=1
                    attr[label]["family_"+g["family"]]+=1
            emit([k,i,g["Audit_id"],g["family"],int(g["exact_gain"]),int(g["compact_gain"]),
                  ",".join(map(str,nonused)),*(",".join(map(str,s)) for s in slots)])
    for k in ("B","C"):
        for metric in ("exact","compact"):
            count=sum(v for t,v in attr[k+"_"+metric].items() if t.startswith("family_"))
            check(count==expected["gains"].get(k+"_"+metric,0),"missing gain rows")
    return dict(case=case,cohort="historical_INCOMPLETE_UNWINDING" if case==CASES[-1] else "SAT_to_UNSAT_repair",
                actual_UsedLeaf_additions=len(add_u),all_ordinary_additions=len(added),proposal_decisions=d["composition"],
                logical=expected["pre_limit"],gains_vs_A=expected["gains"],losses_vs_A=expected["lost_vs_A"],
                compact_first512_counts={k:min(512,v["compact"]) for k,v in expected["pre_limit"].items()},
                gain_births_by_map=per,distinct_gain_ordinals=len(union),attribution=attr,compact_only_gains=both)


def main(droot,dest):
    data=[analyze(case,droot,dest/case) for case in CASES]
    totals={}
    for name,items in (("three_repairs",data[:3]),("historical",data[3:]),("all",data)):
        total={k:Counter() for k in MATRIX}
        at=defaultdict(Counter)
        for item in items:
            for arm in MATRIX:total[arm].update(item["logical"][arm])
            for key,counts in item["attribution"].items():at[key].update(counts)
        totals[name]=dict(logical=total,attribution=at,added_UsedLeaf=sum(d["actual_UsedLeaf_additions"] for d in items))
    check(totals["all"]["logical"]["A"]=={"exact":395,"compact":322} and totals["all"]["added_UsedLeaf"]==3679,
          "sealed A or UsedLeaf baseline differs")
    save(dest/"summary.json",dict(revision="4ddaf2843f6f51f1d0621ef2fa155783d402dac2",phase="SI-1B-review",
        status="READY_FOR_REVIEW",cases=data,totals=totals,added_native_solver_runs=0,SAT_RUP_Closure_rechecks=[0,0,0]))
    index={}
    for p in sorted(dest.rglob("*")):
        if p.is_file() and p!=dest/"files.json":
            index[str(p.relative_to(dest))]=dict(bytes=p.stat().st_size,sha256=digest(p))
    save(dest/"files.json",index)


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("d43d_restored",type=Path)
    ap.add_argument("output",type=Path)
    args=ap.parse_args()
    main(args.d43d_restored,args.output)
