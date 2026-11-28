"""Offline counterfactual. Change only the old occurrence focus and compare the signed injections."""
import argparse
from pathlib import Path
import subprocess
from audit_d42 import table,keyed,native_n
from cases42 import load
from d43_project_support import check,digest,save


def check_role(path):
    forbidden=set()
    with path.open() as f:
        for line in f:
            if line.startswith("GUARD\t"):
                raw=[int(line.rsplit("\t",1)[1])]
            elif line.startswith("EDGE\t"):
                x=line.split("\t");raw=[int(x[4]),int(x[7])]
            elif line.startswith("CO\t"):
                raw=list(map(int,line.split()[3:]))
            else:continue
            forbidden.update(l//2 for l in raw if l>=2)
    return forbidden


def one(case,matrix,old,audit,d42,tool,out):
    prefix=matrix/case
    p0=prefix/"compact/P0/native/model.tsv";p1=prefix/"compact-reuse/P1/native"
    output=out/case;output.mkdir(parents=True,exist_ok=False)
    counts=[native_n(p0),native_n(p1/"boundary.tsv")]
    subprocess.run([tool,old/case/"compact-audit/native/proof.bin",p0,p1/"boundary.tsv",p1/"delta/variables.tsv",
        p1/"delta/declarations.txt",output,*map(str,counts),"structure"],check=True)
    hist=d42/"functional"/case/"1/Mapping-only/P1/native/effective-map.tsv"
    check(digest(hist)==digest(output/"effective-map.tsv"),"old occurrence focus no longer reproduces the historical signed correspondence")
    seeds=[{},{}];ordinary=[set(),set()]
    for line in (p1/"delta/variables.tsv").open():
        s,v,p,role,*_=line.split();s,v,p=map(int,(s,v,p))
        if p>=0:seeds[s][v]=p
        if role in ("Aux","Value"):ordinary[s].add(v)
    blocked=[check_role(p0),check_role(p1/"boundary.tsv")]
    for row in table(p1/"effective-map.tsv"):
        s,v,p=map(int,(row["side"],row["variable"],row["peer"]))
        if v in seeds[s]:check(seeds[s][v]==p,"semantic anchor changed")
        elif p>=0:
            check(v in ordinary[s] and v not in blocked[s] and p//2 in ordinary[1-s] and
                  p//2 not in blocked[1-s] and int(row["ordinary"]),"structural change of a theory port or alias")
    legacy=keyed(output/"transport.tsv");fresh=keyed(p1/"structure-stats.tsv")
    used=sum(1 for row in table(audit/case/"inputs42.tsv") if int(row["use"])&2)
    check(fresh["checks"]<=1000000 and fresh["rounds"]<=4,"structural budget")
    item=dict(case=case,old_proposal_input_count=used,compact_membership_input_count=fresh["old_checked"],
        old_focus_rounds=legacy["rounds"],actual_rounds=fresh["rounds"],old_added=legacy["added"],actual_added=fresh["added"],
        old_checks=legacy["checks"],actual_checks=fresh["checks"],old_stop=legacy["stop"],actual_stop=fresh["stop"],
        previous_mu_sha256=digest(hist),rerun_old_focus_mu_sha256=digest(output/"effective-map.tsv"),
        actual_mu_sha256=digest(p1/"effective-map.tsv"),semantic_anchor_pairs=len(seeds[0]),forbidden_structural_endpoints=0)
    save(output/"control.json",item);return item


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("matrix","B","audit","D42","tool","out"):p.add_argument(k,type=Path)
    a=p.parse_args();results=[one(c,a.matrix,a.B,a.audit,a.D42,a.tool,a.out) for c in load()]
    save(a.out/"controls.json",results)
