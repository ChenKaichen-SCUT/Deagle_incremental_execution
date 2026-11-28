"""Independent offline audit. The full Audit archive is an input to this process only."""
import argparse
from collections import Counter,defaultdict
import csv
import json
from pathlib import Path
import struct
import subprocess

from audit_d42 import imports, native_n
from audit_d43b import Library
from cases42 import load
from d43_owner_probe import stream_receipt
from d43_project_support import check, digest, first_members, save, signed_map, translated
from run_stock import BASE


def table(path):
    with path.open() as f:
        yield from csv.DictReader(f,delimiter="\t")


def batches(path, header=False):
    pool={}
    with path.open() as f:
        if header:next(f)
        for line in f:
            i,family,n,*c=line.split();c=list(map(int,c));i=int(i)
            check(len(c)==int(n) and i not in pool,"invalid eligible batch")
            pool[i]=(family,c)
    return pool


def model_digest(model,meta):
    return stream_receipt(model,Path(json.loads(meta.read_bytes())["cwd"]))["canonical_sha256"]


def certificates(path):
    with path.open() as f:
        return {tuple(map(int,v[1:5])):v[5] for line in f if (v:=line.split()) and v[0]=="D"}


def verify_static(old,new,prod,lib,mu,out):
    pool=first_members(new);stats=Counter();dirty=[set(),set()]
    claims={int(r["occurrence"]):int(r["P1_permanent_occurrence"]) for r in table(prod/"input-matches.tsv")}
    proposals=list(table(prod/"structure.tsv"))
    old_sites=defaultdict(list);new_sites=defaultdict(list)
    for row in proposals:
        v=int(row["old_var"]);p=int(row["new_signed_positive"])
        check(mu[v]==p,"proposal different from common map")
        old_sites[int(row["old_occurrence"])].append((v,p))
        new_sites[int(row["new_occurrence"])].append(v)
    witness={};n=0
    with new.open() as f:
        for row in f:
            if row.startswith("C\t"):
                n+=1
                if n in new_sites:
                    _,scope,*c=row.split();check(scope=="B","structural target in scope")
                    for v in new_sites[n]:witness[v]=tuple(sorted(set(map(int,c))))
    n=0
    with old.open() as f,(out/"inputs").open("x") as audit:
        for line in f:
            if not line.startswith("C\t"):continue
            _,scope,*c=line.split();lits=list(map(int,c));n+=1
            g=lib.b[n-1];need_old=lib.observed(0,n-1) or (scope=="B" and lib.slots[0][g]==1023)
            check(scope==("Q" if g==0xffffffff else "U" if g==0xfffffffe else "B"),"original scope")
            dest=[translated(l,mu) for l in lits]
            valid=None not in dest
            key=tuple(sorted(set(dest))) if valid else None
            present=pool.get(key,0) if scope=="B" else 0
            print(scope,int(not present),*lits,file=audit)
            for v,p in old_sites.get(n,()):
                check(scope=="B" and lib.observed(0,n-1) and key==witness[v] and v in {l//2 for l in lits},
                      "structural proposal lacks its signed static witness")
            if need_old:
                recorded=claims.pop(n)
                check(recorded==(present if valid else -1),"full P1 clause membership disagrees")
                state="matched" if present else "mapped_absent" if valid else "unmapped"
                stats["B_"+state]+=1
                if not present:dirty[0].add(lib.slots[0][g])
    check(not claims and n==len(lib.b),"Boolean UsedLeaf coverage")
    cert=certificates(prod/"delta/declarations.txt")
    checked={tuple(int(r[k]) for k in ("op","a","b","c")):r for r in table(prod/"theory-matches.tsv")}
    for fact,(j,g) in lib.t.items():
        if lib.observed(1,j) or lib.slots[1][g]==1023:
            state=cert[fact];r=checked.pop(fact)
            check(r["state"]==state and int(r["slot"])==lib.slots[1][g] and int(r["observed"])==lib.observed(1,j),
                  "theory observation differs")
            stats["T_"+state]+=1
            if state!="M":dirty[1].add(lib.slots[1][g])
    check(not checked,"extra theory claims")
    return stats,dirty


def audit(case,root,bmat,historical,ref_tools,native_learns,out):
    out.mkdir(parents=True,exist_ok=False)
    arm=root/case;producer=arm/"compact/P0";old=producer/"native/model.tsv"
    prod=arm/"compact-reuse/P1/native";new=prod/"boundary.tsv"
    dual=bmat/case/"compact-audit";prior=historical/"functional"/case/"1/Mapping-only/P1"
    dense=producer/"native/dense.bin"
    check(digest(dense)==digest(dual/"native/dense.bin"),"new production birth/tag stream differs from audited B")
    fixed_index=BASE/"reports/evidence/d43b/raw/files.json"
    check(digest(fixed_index)=="4468d5f2acb74072c8a8743797587e2f47f1372d5456dbdf0455c66b447ebccb","B archive index")
    ix=json.loads(fixed_index.read_bytes())["files"]
    proof=dual/"native/proof.bin"
    for name in ("proof.bin","dense.bin","model.tsv"):
        check(digest(dual/"native"/name)==ix[f"accepted/{case}/compact-audit/native/{name}"]["sha256"],"B origin")
    check(model_digest(old,producer/"run.json")==model_digest(dual/"native/model.tsv",dual/"run.json"),
          "actual old model differs from the independently captured proof")
    check(model_digest(new,prod.parent/"run.json")==model_digest(prior/"native/boundary.tsv",prior/"run.json"),
          "frozen P1 and live P1 models differ")
    check(certificates(prod/"delta/declarations.txt")==certificates(prior/"native/delta/declarations.txt"),
          "strict old/new theory binding certification changed")
    lib=Library(dense);mu=signed_map(prod/"effective-map.tsv")
    previous_mu=signed_map(prior/"native/effective-map.tsv")
    changes=Counter()
    with (out/"mapping-changes.tsv").open("x") as file:
        print("old_variable\tprevious_positive\tcurrent_positive",file=file)
        for v,(p,q) in enumerate(zip(previous_mu,mu,strict=True)):
            if p==q:continue
            changes["added" if p<0 else "lost" if q<0 else "different_signed_peer"]+=1
            print(v,p,q,sep="\t",file=file)
    n0=len(mu);n1=native_n(new)
    with (out/"map").open("x") as f:
        for i,p in enumerate(mu):
            if p>=0:print(i,p,file=f)
    with (out/"directed-vars.tsv").open("x") as f:
        for r in table(prod/"effective-map.tsv"):
            print(r["side"],r["variable"],r["peer"],"Aux" if int(r["ordinary"]) else "Interface","given",0,sep="\t",file=f)
    checked,actual=verify_static(old,new,prod,lib,mu,out)
    declared=json.loads((prod/"compact-delta.json").read_bytes())["dirty_slots"]
    check([sorted(s) for s in actual]==declared,"production Dirty mismatch")
    # Feed the fixed effective correspondence to the old exact graph selector. No structural search here.
    subprocess.run([ref_tools/"select42",proof,old,new,out/"directed-vars.tsv",prod/"delta/declarations.txt",
                    out,str(n0),str(n1),"semantic"],check=True)
    subprocess.run([ref_tools/"check",proof,out/"inputs",out/"map",native_learns,prod/"delta/declarations.txt",out],check=True)
    cat=list(table(out/"catalog42.tsv"));ids={int(r["native_id"]):int(r["ordinal"]) for r in cat}
    exact=batches(out/"batch-rows.tsv");witness={}
    with (out/"survivors.tsv").open() as f:
        for line in f:
            i,*c=map(int,line.split());witness[ids[i]]=c
    check(witness=={i:c for i,(_,c) in exact.items()},"independent resolution/Closure replay disagrees with exact transport")
    compact=batches(prod/"eligible.tsv");selected=batches(prod/"ready.tsv",True)
    check(all(exact.get(i)==row for i,row in compact.items()) and selected==dict(list(compact.items())[:512]),
          "compact false admission or selection order")
    check(not imports(arm/"compact-cold/P1/native"),"cold attached an imported clause");hits=imports(prod)
    check(hits<=selected.keys(),"unknown imported ordinal")
    old_exact=batches(prior/"native/batch-rows.tsv")
    old_compact={int(r["ordinal"]) for r in table(BASE/"reports/evidence/d43b/cases"/case/"eligible.tsv")}
    check(max(map(len,lib.keys))<=1023,"overflow in a real cohort requires logical projection oracle")
    ua=[set(),set()]
    for r in table(out/"inputs42.tsv"):
        if int(r["use"])&2 and r["status"]!="matched":
            i=int(r["occurrence"])-1;check(lib.observed(0,i),"missing exportable Boolean leaf")
            ua[0].add(lib.slots[0][lib.b[i]])
    for r in table(out/"facts42.tsv"):
        if int(r["use"])&2 and r["status"]!="M":
            i,g=lib.t[tuple(int(r[k]) for k in ("op","a","b","c"))]
            check(lib.observed(1,i),"missing exportable theory leaf")
            ua[1].add(lib.slots[1][g])
    check(all(s<=t for s,t in zip(ua,actual)),"U_audit outside U_actual")
    masks=[sum(1<<s for s in group) for group in ua]
    counts=defaultdict(Counter);reasons=Counter()
    with (out/"actual-mu-births.tsv").open("x") as log,(out/"learned.tsv").open() as learned:
        print("ordinal\tclass\tscope\tmapped\texact\tlogical_Uaudit\tlogical_Uactual\tcompact\tselected\thit\tAudit_causes",file=log)
        for (i,flags,c,b,t),row,detail in zip(lib.births(),cat,learned,strict=True):
            audit_id,size,audit_flags,direct,cause,*_=map(int,detail.split())
            check(i==int(row["ordinal"]) and audit_id==int(row["native_id"]),"misaligned Audit birth")
            fam=("scope_only","B","T","M")[flags&3] if flags&3 or flags&12 else "B"
            permanent=not flags&12;mapped=int(row["conclusion_mapped"])
            ref=i in exact;group=permanent and mapped and not (b&masks[0] or t&masks[1])
            keep=i in compact
            if permanent:
                check(bool(mapped)==all(translated(l,mu) is not None for (l,) in struct.iter_unpack("<i",c)),"conclusion mismatch")
                check(not group or ref,"logical group false admission")
                check(not keep or group,"observed grouping larger than exact leaf union")
                stats=counts[fam];stats["permanent"]+=1;stats["mapped"]+=mapped;stats["exact"]+=ref
                stats["unmapped_conclusion"]+=not mapped;stats["mapped_but_exact_dead"]+=bool(mapped and not ref)
                stats["logical_Uaudit"]+=bool(group);stats["same_group_loss"]+=ref and not group
                stats["extra_UsedLeaf_loss"]+=bool(group and not keep);stats["overflow_loss"]+=0
                stats["logical_Uactual"]+=keep;stats["compact"]+=keep;stats["selected"]+=i in selected;stats["hit"]+=i in hits
                if mapped and not ref:reasons[str(cause)]+=1
            print(i,fam,"permanent" if permanent else "unknown" if flags&8 else "query",mapped,int(ref),int(group),
                  int(keep),int(keep),int(i in selected),int(i in hits),cause,sep="\t",file=log)
    scalar=dict(case=case,births=len(cat),registered_groups=list(map(len,lib.keys)),static_checked=checked,
        mapped_old=sum(v>=0 for v in previous_mu),mapped_current=sum(v>=0 for v in mu),
        changed_images=changes,previous_exact=len(old_exact),actual_exact=len(exact),previous_compact=len(old_compact),
        actual_compact=len(compact),exact_gained=sorted(exact.keys()-old_exact.keys()),exact_lost=sorted(old_exact.keys()-exact.keys()),
        compact_gained=sorted(compact.keys()-old_compact),compact_lost=sorted(old_compact-compact.keys()),
        classes=counts,overlapping_Audit_cause_masks_for_mapped_dead=reasons,selected=len(selected),hit=len(hits),
        false_admissions=0,independent_replay_equal=True,actual_mu_sha256=digest(prod/"effective-map.tsv"))
    save(out/"audit.json",scalar);return scalar


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("matrix","B_matrix","D42","ref_tools","oracles","out"):p.add_argument(arg,type=Path)
    p.add_argument("--case",action="append");a=p.parse_args()
    for case in a.case or load():
        src=a.oracles/case/"native-learns.tsv"
        print(audit(case,a.matrix,a.B_matrix,a.D42,a.ref_tools,src,a.out/case)["actual_exact"],case,flush=True)
