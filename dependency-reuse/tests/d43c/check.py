"""Check all native micro boundaries, D1 oracle agreement, branch rollback and the two mutation campaigns."""
import argparse
import json
from pathlib import Path
from faults import Campaign,SmallProof,Library,check,save
from audit_d43c import slots,run_checker
from verify_d3_boundary import verify
from contracts import controls,structural_controls


def branch_check(folder, stream):
    lib=Library(folder/"scope.bin.dense");g=SmallProof(folder/"scope.bin")
    rows=[list(map(int,s.split())) for s in stream.read_text().splitlines()]
    check(len(rows)==2 and rows[0][0]!=rows[1][0],"branch controls must have different choices")
    for row in rows:
        binding,node,op,n=row[:4];cond=row[4:4+n];bits=row[4+n:-2]
        check(row[-2:]==[0,0] and len(bits)==16,"undone branch left a native edge")
        check(g.facts[node][0]==op,"branch tag/ProofID disagreement")
        expected=g.T[node]
        active={x[3] for x in expected if x[0] in (3,4) and x[3]>=0}
        check(active==set(cond)=={binding},"branch RF conditions do not match")
        for fact in expected:
            index,group=lib.t[fact];slot=lib.slots[1][group]
            check(lib.observed(1,index) and bits[slot//64]&(1<<(slot%64)),"stale theory tag after native backtrack")
    return [r[1] for r in rows]


def fixture_checks(fixtures,micro,checker,out):
    result={}
    for d in sorted(fixtures.iterdir()):
        if d.name=="branch-edges":continue
        lib=Library(d/"dense.bin");slots(lib,d/"T-slots.tsv")
        counts=run_checker(checker,d/"proof.bin",d/"decl",d/"T-slots.tsv",d/"boundaries.bin",d/"boundaries.bin.cert")
        counts["checked_permanent_births"]=SmallProof(d/"proof.bin").check_births(d/"dense.bin")
        for sub in ("triplets","d4"):
            independent=micro/sub/d.name/"oracle/native-theory.tsv"
            if independent.is_file():
                counts["frozen_D1_boundary_counts"]=verify(d/"proof.bin",independent,native_fixture=True)
                break
        result[d.name]=counts
    d=fixtures/"shorten-empty";lib=Library(d/"dense.bin");g=SmallProof(d/"proof.bin")
    check(all(lib.observed(0,i) for i in range(3)) and len(lib.b)==3 and
          any(k==4 and len(l)==1 for (_,_,k,_),l in zip(g.nodes,g.lits)) and
          any(k==4 and not l for (_,_,k,_),l in zip(g.nodes,g.lits)),"shortened unit/empty support missing")
    result["shorten-empty"]["exact_used_occurrences"]=[1,2,3]
    clean=fixtures/"branch-edges/scope.bin.branches";ids=branch_check(clean.parent,clean)
    result["branch-edges"]=dict(Audit_ProofIDs=ids,backtrack_in_out_zero=True)
    save(out/"fixtures.json",result)
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("B_matrix","C_matrix","fixtures","micro","D42","B_overflow","permutations","real_audit","checker","out"):
        p.add_argument(key,type=Path)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
    fixture_checks(a.fixtures,a.micro,a.checker,a.out)
    c=Campaign(a.fixtures,a.out/"faults",a.checker)
    c.learning();c.scoped_and_theory();c.boundaries(a.C_matrix/"fib_updates_8/compact-audit/native",
        a.D42/"functional/fib_updates_8/1/Mapping-only/P1/native/delta/declarations.txt",
        a.real_audit/"fib_updates_8/T-slots.tsv")
    c.changed(a.micro/"d4");c.archive(a.fixtures/"root-chain")
    structural_controls(c,a.B_matrix,a.micro/"d4")
    controls(c,a.B_matrix,a.B_overflow,a.fixtures,a.permutations)
    path=a.fixtures/"branch-edges/scope.bin.branches";rows=[r.split() for r in path.read_text().splitlines()]
    n0,n1=int(rows[0][3]),int(rows[1][3])
    rows[1][4+n1:4+n1+16]=rows[0][4+n0:4+n0+16]
    mutant=c.out/"rolled-back-RF-tag.tsv";mutant.write_text("".join(" ".join(r)+"\n" for r in rows))
    c.reject("tag_from_previous_RF_branch",lambda:branch_check(path.parent,mutant),
             ["stale theory tag after native backtrack"],dict(first_ID=int(rows[0][1]),second_ID=int(rows[1][1])))
    save(a.out/"rejections.json",c.results)
    print(len(c.results),"independent rejections")
