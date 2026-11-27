"""D1 regression checks using a real frozen manifest, native C programs and an alias fixture."""
import argparse
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"scripts"))
from run_stock import ENV
from diff_d1 import digest


def load_jsonl(path):
    with gzip.open(path, "rt") as f:
        return [json.loads(line) for line in f]


def permute(source, dest):
    rows = [line.rstrip("\n").split("\t") for line in source.open()]
    n = int(next(r[1] for r in rows if r[0] == "N"))
    sizes = {t:sum(r[0] == t for r in rows) for t in ("S","X","NODE")}
    assert not any(r[0] == "CO" for r in rows), "fixture expects static SAT allocation"
    def literal(s):
        i = int(s)
        if i < 0: return s
        v = i//2
        return str(2*(n-v) + ((i & 1) ^ (v % 3 == 1)))
    def sid(s):
        return str(sizes["S"]+1-int(s))
    def ctx(s):
        return str(sizes["X"]+1-int(s)) if int(s)>0 else s
    def node(s):
        return str(sizes["NODE"]-1-int(s)) if int(s)>=0 else s
    names = {}
    def name(s):
        return names.setdefault(s,"renamed_"+str(len(names)+1))
    with dest.open("x") as file:
        for r in rows:
            t = r[0]
            if t == "S":
                r[1],r[6] = sid(r[1]),"90000"
            elif t == "X":
                r[1:5] = [ctx(r[1]),sid(r[2]),ctx(r[3]),ctx(r[4])]
                r[5::2] = [sid(i) for i in r[5::2]]
            elif t in ("V","E"):
                r[1:3] = [name(r[1]),ctx(r[2])]
            elif t == "A":
                r[1], r[4] = name(r[1]),literal(r[4])
            elif t == "NODE":
                r[1],r[2],r[3],r[6] = node(r[1]),name(r[2]),str(900000-int(r[3])),node(r[6])
            elif t in ("IN","OUT","MEMBER"):
                r[1:] = [node(i) for i in r[1:]]
            elif t == "F":
                r[1:] = [name(s) for s in r[1:]]
            elif t in ("H","VALUE_DEF"):
                r[1] = name(r[1])
            elif t == "TERM" and r[2] == "symbol":
                r[4] = name(r[4])
            elif t == "EDGE":
                r[2:] = [name(r[2]),name(r[3]),literal(r[4]),node(r[5]),node(r[6]),literal(r[7])]
            elif t == "GUARD":
                r[1:] = [name(r[1]),literal(r[2])]
            elif t in ("C","G","N"):
                r[2:] = [literal(i) for i in r[2:]]
            file.write("\t".join(r)+"\n")
    return literal


def difference(a,b,engine,out):
    subprocess.run([sys.executable,ROOT/"scripts/diff_d1.py",a,b,engine,out],check=True)
    return json.loads((out/"summary.json").read_text())


def aliases(path, split):
    # x/y alias in P0 and split in P1. z becomes constant. A gate uses a
    # forbidden alias as a parent; the unrelated input w and its negation survive.
    rows = [["DEAGLE-D1","1"],["K","SC"],["QUERY"],["TARGET","p"]]
    for i,sym in enumerate("xyzw",1):
        rows.extend([["S",i,"site-"+sym,"unique","f","sample.c",i],
                     ["X",i,i,0,0],["V",sym,i,"assign0",sym,"bool","static"]])
        lit = ([2,2,4,6] if not split else [4,8,-1,11])[i-1]
        rows.append(["A",sym,"bool",0,lit])
    rows += [["G","and",12,2,6],["C","B",6,7],["C","B",6,7],
             ["C","Q",6],["C","U",2],["N",9],["END",0]]
    if split:
        for i in (-6,-5):
            rows[i] = ["C","B",10,11]
        rows[-4] = ["C","Q",11]
        rows[-3] = ["C","U",4]
    path.write_text("".join("\t".join(map(str,r))+"\n" for r in rows))


def graph_fixture(path, merged):
    rows = [["DEAGLE-D1",1],["K","SC"],["QUERY"],["TARGET","p"],["TERM",1,"constant","bool","true"]]
    nodes = ("w","r","z") if merged else ("w","r")
    for i,name in enumerate(nodes):
        role = "read" if name == "r" else "write"
        rows += [["S",i+1,name,"unique","f","test.c",i+1],["X",i+1,i+1,0,0],
                 ["E",name,i+1,role,"6:symbol1:x","unsignedbv:32","static"],
                 ["NODE",i,name,0,"r" if role=="read" else "","w" if role=="write" else "",
                  0 if merged and i==1 else i],["MEMBER",0 if merged and i==1 else i,i]]
        if role=="write": rows += [["H",name,1],["GUARD",name,-1]]
    rows += [["EDGE","rf","w","r",2,0,1,2],["F","choice","w","r"],["A","choice","bool",0,2]]
    if merged:
        rows += [["EDGE","rf","z","r",4,2,1,4],["EDGE","apo","w","r",-1,-1,-1,-2],
                 ["OUT",0,1],["IN",1,0]]
    rows += [["C","B",2],["C","Q",3],["N",4]]
    if merged: rows += [["CO",0,2,8,10,-1,-1]]
    rows += [["END",0]]
    path.write_text("".join("\t".join(map(str,r))+"\n" for r in rows))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ("native","engine","real_manifest","new_directory"):
        p.add_argument(arg,type=Path)
    a = p.parse_args()
    native,engine,real,out = [p.resolve() for p in (a.native,a.engine,a.real_manifest,a.new_directory)]
    out.mkdir(parents=True,exist_ok=False)
    changed = out/"renumber.tsv"
    lit = permute(real,changed)
    ref = difference(real,real,engine,out/"self")
    remap = difference(real,changed,engine,out/"renumber")
    assert remap["variables"]["matched"] == ref["variables"]["matched"] > 0
    assert remap["clauses"]["occurrences"] == ref["clauses"]["occurrences"]
    assert remap["theory"]["occurrences"] == ref["theory"]["occurrences"]
    with gzip.open(out/"renumber/variables.tsv.gz","rt") as file:
        for line in file:
            side,var,peer,*_ = line.split()
            if side == "0" and int(peer) >= 0: assert peer == lit(str(2*int(var)))
    for s in (0,1): aliases(out/f"alias{s}.tsv",s)
    alias = difference(out/"alias0.tsv",out/"alias1.tsv",engine,out/"alias")
    with gzip.open(out/"alias/variables.tsv.gz","rt") as f:
        v = {(int(s),int(i)):(int(peer),why) for s,i,peer,role,why,key in (line.split() for line in f)}
    assert v[0,1][0] == -1 and v[0,2][0] == -1 and v[0,6][0] == -1
    assert v[0,3][0] == 11 and "peer_constant_fold" in v[0,2][1]
    assert alias["clauses"]["occurrences"]["U"]["P0_unknown"] == 1
    assert alias["clauses"]["occurrences"]["B"]["P0_matched"] == 2
    assert alias["clauses"]["distinct_resolved_keys"]["B"]["P0_matched"] == 1
    assert alias["clauses"]["occurrences"]["Q"]["P0_matched"] == 1

    scoped = out/"different-query.tsv"
    scoped.write_text((out/"alias1.tsv").read_text().replace("TARGET\tp\n","TARGET\tother\n"))
    different = difference(out/"alias0.tsv",scoped,engine,out/"query")["clauses"]["occurrences"]
    assert different["B"]["P0_matched"] == 2 and different["Q"]["P0_unknown"] == 1

    for s in (0,1): graph_fixture(out/f"graph{s}.tsv",s)
    graph = difference(out/"graph0.tsv",out/"graph1.tsv",engine,out/"graph")["theory"]["occurrences"]
    assert graph["BlockCertificate"].get("P0_retired") == 2
    for kind in ("CompleteRFDomain","CompleteWriteDomain"):
        assert graph[kind].get("P0_retired") == graph[kind].get("P1_added") == 1
    assert graph["RFBinding"].get("P0_matched") == 1 and graph["DynamicCO"].get("P1_unknown") == 1
    truncated = out/"incomplete.tsv"
    truncated.write_text((out/"graph0.tsv").read_text().rsplit("END",1)[0])
    from d1_identity import Keys, Model
    try:
        Model(truncated,Keys())
    except ValueError:
        pass
    else:
        raise AssertionError("truncated manifest accepted")

    template = (Path(__file__).with_name("local.c")).read_text()
    variants = {"base":template, "local":template.replace("unrelated = 1;", "unrelated = 17;\n  unrelated += 1;"),
                "guard":template.replace("value = 7;", "if(enabled) value = 7;")}
    native_runs = {}
    for label,source in variants.items():
        d = out/label
        d.mkdir()
        (d/"case.c").write_text(source)
        cmd = [str(native),"--d1-manifest","native.tsv","--function","main","--deagle-closure","--mm","sc",
               "--64","--unwind","4","--unwinding-assertions","--json-ui","case.c"]
        with (d/"stdout").open("w") as stdout, (d/"stderr").open("w") as stderr:
            proc = subprocess.run(cmd,cwd=d,env=ENV,stdout=stdout,stderr=stderr,timeout=60,
                                  preexec_fn=lambda:os.sched_setaffinity(0,{0}))
        assert proc.returncode == (10 if label == "guard" else 0)
        native_runs[label] = dict(argv=cmd,rc=proc.returncode,native_sha256=digest(d/"native.tsv"))
    for label in ("local","guard"):
        d = out/("compare-"+label)
        result = difference(out/"base/native.tsv",out/label/"native.tsv",engine,d)
        assert result["clauses"]["occurrences"]["B"].get("P0_matched",0)
        dec = load_jsonl(d/"declarations.jsonl.gz")
        assert any(s == 0 and kind == "RFBinding" and state == "matched" and loc[0].startswith("value#")
                   for s,kind,loc,slot,key,state,why in dec)
        if label == "guard":
            changed = [r for r in dec if r[1]=="GuardBinding" and r[2][0].startswith("value#")
                       and r[6]=="guard_literal_form_changed"]
            assert {r[5] for r in changed} == {"retired","added"}
            assert any(r[1]=="GuardDefinition" and r[5]=="retired" and r[2].startswith("value#") for r in dec)
    (out/"checks.json").write_text(json.dumps(dict(renumber_checked_variables=ref["variables"]["matched"],
        renumber_clauses=ref["clauses"]["occurrences"],alias_probe=alias["variables"],native=native_runs,
        guard_transition=changed,local_and_guard_unaffected_rf=True,block_merge_and_domain=graph,
        incomplete_manifest_rejected=True,different_target_separates_Q=True),indent=2)+"\n")
    print("D1 regression checks passed")


if __name__ == "__main__":
    main()
