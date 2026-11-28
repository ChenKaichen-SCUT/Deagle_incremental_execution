"""Rebuild reviewed Compact pools from the full Audit, signed injections and real P1 clauses. Offline only."""
import argparse
from collections import Counter
import hashlib
from pathlib import Path

from audit_d43d import batches
from cases42 import load
from compact43 import DenseLibrary
from si1b_review import run as recompute, translation
from si1b_review_proof import Proof
from si1b_review_space import BASE, EVIDENCE, check, digest, read, rows, save, sign_inverse, table
from si1b_value_boundary import model_certificate


def emit(nvars, pool):
    lines=[f"D4-selected-v1\t{nvars}\t{len(pool)}"]
    for ordinal,_,family,_,lits in pool:
        lines.append("\t".join(map(str,(ordinal,family,len(lits),*lits))))
    return ("\n".join(lines)+"\n").encode()


def freeze(case,spec,droot,broot,work,output):
    archived=EVIDENCE/"si1b-review"/case
    fresh=work/"review"
    audit_dir=work/"audit"
    recompute(case,droot,broot,fresh,audit_dir)
    for name in ("births.tsv.gz","composition.tsv.gz","boolean-leaves.tsv.gz","theory-leaves.tsv.gz","results.json"):
        check(digest(fresh/name)==digest(archived/name),"review must reproduce: "+name)
    result=read(fresh/"results.json")
    old=droot/"matrix"/case/"compact/P0/native"
    prior=droot/"matrix"/case/"compact-reuse/P1/native"
    p1=prior/"boundary.tsv"
    archive=broot/case/"compact-audit/native/proof.bin"
    proof=Proof(archive)
    dense=DenseLibrary((old/"dense.bin").read_bytes())
    maps={"A":{int(r["variable"]):int(r["peer"]) for r in rows(prior/"effective-map.tsv") if r["side"]=="0" and int(r["peer"])>=2},
          "B":{int(r["old_variable"]):int(r["positive_image"]) for r in rows(EVIDENCE/"si1b"/case/"join/direct-map.tsv.gz")}}
    maps["C"]=maps["A"]|{int(r["old"]):int(r["B_positive"]) for r in rows(fresh/"composition.tsv.gz") if r["decision"]=="added_certified_ordinary"}
    plan=read(BASE/"configs/si1b-value.json")
    ids=plan["knowledge"][case]
    model=model_certificate(p1,Path(read(prior.parent/"run.json")["cwd"]))
    frozen=result["native_space"][1]
    check(model["canonical"]==frozen["first_root_model_sha256"] and model["nvars"]==frozen["boundary"][0],"unaligned P1")
    roles=["A",ids["new"]]
    if ids.get("require_B_C_identical"):roles.append("C")
    out=output/case
    out.mkdir(parents=True)
    pools={k:[] for k in roles}
    independent={k:batches(audit_dir/k/"batch-rows.tsv") for k in roles}
    receipt={}
    for k in roles:
        sign_inverse(maps[k])
        receipt[k]=dict(mapped=len(maps[k]),negative_images=sum(n&1 for n in maps[k].values()),
            signed_map_sha256=hashlib.sha256("".join(f"{v}\t{n}\n" for v,n in sorted(maps[k].items())).encode()).hexdigest(),
            exact_union=len(independent[k]),reference_catalog_sha256=digest(audit_dir/k/"catalog42.tsv"))
    for (i,flags,clause,_,_),row in zip(dense.births(),rows(fresh/"births.tsv.gz"),strict=True):
        check(i==int(row["ordinal"]) and proof.birth_ids[i-1]==int(row["Audit_id"]),"native birth directory")
        for k in roles:
            if row[k+"_compact"]!="1":continue
            node=int(row["Audit_id"]); family=row["family"]
            check(clause is not None and not flags&12 and proof.clause(node)==clause and row[k+"_exact"]=="1","nonpermanent or wrong Audit clause")
            dest=translation(clause,maps[k])
            check(dest is not None and independent[k].get(i)==(family,dest),"not the exact-selector signed conclusion")
            pools[k].append((i,node,family,clause,dest))
    proof.close()
    nvars=model["nvars"]
    for k in roles:
        receipt[k].update(all_logical=len(pools[k]),pool_sha256=hashlib.sha256(emit(nvars,pools[k])).hexdigest(),
                          family=Counter(x[2] for x in pools[k]))
    if ids.get("require_B_C_identical"):
        check(pools["B"]==pools["C"] and len(pools["B"])==389 and receipt["B"]["family"]=={"B":55,"M":334},
              "fib B and C differ in birth, class, old or signed new literals or sequence")
    selected={}
    batch_info={}
    for (arm,k),expected in zip((("A","A"),("new",ids["new"])),ids["expected_compact"]):
        pool=pools[k]
        check([p[0] for p in pool]==sorted({p[0] for p in pool}) and len(pool)==expected,"unexpected pool")
        withheld=pool[512:]
        selected[arm]={p[0]:p for p in pool[:512]}
        path=out/(arm+".ready.tsv")
        path.write_bytes(emit(nvars,pool[:512]))
        if arm=="A":
            check(path.read_bytes()==(prior/"ready.tsv").read_bytes(),"original A batch differs")
        with table(out/(arm+".pool.tsv.gz"),"ordinal Audit_id family chosen old_literals translated_literals") as put:
            for o,node,family,old_ls,dest in pool:
                put([o,node,family,int(o in selected[arm])," ".join(map(str,old_ls))," ".join(map(str,dest))])
        batch_info[arm]=dict(mu=k,eligible=len(pool),selected=len(selected[arm]),withheld=len(withheld),
                            selected_family=Counter(p[2] for p in pool[:512]),sha256=digest(path))
    same=sorted(selected["A"].keys()&selected["new"].keys())
    check(all(selected["A"][o]==selected["new"][o] for o in same),"same birth with different signed image")
    flags=spec["argv"]; staged={k:spec["files_sha256"][p] for k,p in spec["inputs"]["P1"].items()}
    saved=read(prior.parent/"run.json")
    check(saved["argv"][-len(flags):]==flags and saved["input_sha256"]==staged and saved["limits"]==spec["limits"],"reference configuration")
    seal=dict(format="SI1B-value-diagnostic-v1",review_base=plan["review_base"],case=case,argv=flags,inputs=staged,
              limits=spec["limits"],native_elf=read(EVIDENCE/"d43d/build.json")["production_elf_sha256"],model=model,batches=batch_info,
              signed_maps=receipt,P0_full_audit=digest(archive),P0_compact=digest(old/"dense.bin"),review_births=digest(fresh/"births.tsv.gz"),
              selected_birth_intersection=same,A_selected_outside_new_first512=sorted(selected["A"].keys()-selected["new"].keys()),
              new_selected_outside_A=len(selected["new"].keys()-selected["A"].keys()),P0_solver_calls=0)
    save(out/"seal.json",seal)
    print(case,"shared",len(same),"A outside first512",seal["A_selected_outside_new_first512"],flush=True)
    return digest(out/"seal.json")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("D","B_accepted","scratch","output"):p.add_argument(name,type=Path)
    a=p.parse_args()
    plan=read(BASE/"configs/si1b-value.json")
    locks={case:freeze(case,load()[case],a.D,a.B_accepted,a.scratch/case,a.output) for case in plan["cases"]}
    save(a.output/"batches.json",dict(format="SI1B-value-diagnostic-v1",plan_sha256=digest(BASE/"configs/si1b-value.json"),seals=locks))
