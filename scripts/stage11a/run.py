"""Replay Stage 11A from project archives, entirely offline, with Python 3.10+."""
import argparse
import csv
import gzip
import io
import json
import re
import sys
from pathlib import Path

import clauses
import experiments
import literature
import lock
import real

ROOT=Path(__file__).resolve().parents[2]
FROZEN=ROOT/"reports/evidence/stage-11a"


def fixture_inputs(study):
    ta,fm=literature.examples()
    t=literature.native_input(ta)
    out={"tacas":t,"fm":literature.native_input(fm),"tacas-reverse":t+"po x#2 x#3\n"}
    alias={"S":"r#1","Aread":"r#2","Awrite":"r#3","Dread":"r#4","Dwrite":"r#5"}
    for name,key in (("lock-p1","projection_P1"),("lock-p2","projection_P2_same_boolean_assignment")):
        g=study[key]["input"]
        rows=["write "+alias[e["key"]] for e in g["events"] if e["op"]=="W"]
        for kind in ("apo","rf","po"):
            rows.extend(kind+" "+alias[a]+" "+alias[b] for a,b in g[kind])
        out[name]="\n".join(rows)+"\n"
    return out


def native_evidence(path):
    rank=path/"rank"
    checks={line.split(None,1)[1].rsplit("/",1)[-1]:line.split(None,1)[0]
            for line in (path/"control.sha256").read_text().splitlines()}
    assert checks["native_control.cpp"]==real.sha((ROOT/"scripts/stage11a/native_control.cpp").read_bytes())
    assert checks["deagle_exe"]=="b84a95d9d02e9fc48217373bf71564db1cb8ce4029644936a893aaaaef0a529e"
    assert checks["solver-session"]=="c474a95f9d668619bdc138382bd59b1f070190c8197fa91071f9aca49075c204"
    rows=list(csv.DictReader(io.StringIO((rank/"unchanged.tsv").read_text()),delimiter="\t"))
    assert len(rows)==7 and all(row["shared"]==row["fresh"] for row in rows)
    directions=[s.split() for s in (rank/"rf-direction.tsv").read_text().splitlines()]
    assert [r[1:] for r in directions]==[["0","0","1","obj#1","obj#2"],["0","0","1","obj#2","obj#1"]]
    reports={}
    for label,expected in (("fm",1),("tacas",0),("tacas-reverse",1),("lock-p1",0),("lock-p2",1)):
        txt=(path/(label+".stdout")).read_text()
        vals=re.search(r"Attempts to add co clauses: (\d+)\. Added co clauses: (\d+)\. Total co pairs: (\d+)",txt)
        assert vals and re.search(r"native_lbool "+str(expected)+r"\b",txt)
        assert not (path/(label+".stderr")).read_bytes()
        reports[label]={"result":("SAT","UNSAT")[expected],"co_attempts":int(vals[1]),
                        "co_clauses_added":int(vals[2]),"co_pairs":int(vals[3])}
    assert reports["fm"]["co_clauses_added"]>0
    return {"fixed_graph_assumptions_agree":len(rows),
            "unsat_calls_with_previous_shared_ranks":[int(r["test"]) for r in rows
                if r["shared"]=="1" and int(r["current_keys"])>0 and r["fresh_order"]=="0"],
            "two_sat_calls":{"caller_rank_vectors":[list(map(int,r[2:4])) for r in directions],
                             "current_sequences":[r[4:] for r in directions]},
            "native_controls":reports}


def encode(data,name):
    b=(json.dumps(data,ensure_ascii=False,indent=2,sort_keys=True)+"\n").encode()
    # Fix the gzip OS header as well as mtime across Python and operating systems.
    if name.endswith(".gz"):
        compressed=bytearray(gzip.compress(b,mtime=0))
        compressed[9]=255
        return bytes(compressed)
    return b


def manifest():
    paths=[ROOT/"project_state.json",ROOT/"reports/stage-11a.md"]
    for folder in (ROOT/"scripts/stage11a",FROZEN):
        paths.extend(p for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts
                     and p!=FROZEN/"manifest.json")
    return {"stage":"11A","status":"READY_FOR_REVIEW",
            "stage10":"dca9eb78250426fe5b2aab22aea5ef91025dd24d",
            "project_parent":"ff434538e5eaa78cf8c5e93eb3e41a7ccf06a5ff",
            "sha256":{p.relative_to(ROOT).as_posix():real.sha(p.read_bytes()) for p in sorted(paths)}}


def run(out,native,compare):
    out.mkdir(parents=True,exist_ok=True)
    real_summary,declarations=real.study(ROOT)
    for name,txt in fixture_inputs(real_summary).items():
        assert (ROOT/"scripts/stage11a/fixtures"/(name+".txt")).read_text()==txt
    cases,rejected=experiments.targeted()
    results={"real-delta.json":real_summary,"real-declarations.json.gz":declarations,
             "read-write-lock.json":lock.check(ROOT),"finite-suite.json":experiments.systematic(),
             "edit-cases.json":cases,"refusals.json":rejected,"literal-bindings.json":experiments.check_binding(),
             "literature-histories.json":literature.check(),"mixed-cdcl.json":clauses.mixed_clause(),
             "stage5-replay.json":clauses.stage5(ROOT),"native-verdicts.json":native_evidence(native)}
    for name,result in results.items():
        data=encode(result,name)
        if compare:
            frozen=(FROZEN/name).read_bytes()
            if name.endswith(".gz"):
                assert gzip.decompress(frozen)==gzip.decompress(data),name
            else:
                assert frozen==data,name
        (out/name).write_bytes(data)
    if compare:
        assert json.loads((FROZEN/"manifest.json").read_bytes())==manifest(),"stage file manifest"
    elif out.resolve()==FROZEN.resolve():
        (FROZEN/"manifest.json").write_bytes(encode(manifest(),"manifest.json"))
    print("PASS:",len(results),"evidence files,",results["finite-suite.json"]["directed_updates"],
          "directed updates, two source-state explorations, five native controls, rank residue.")


if __name__=="__main__":
    if not __debug__:
        sys.exit("Replay requires enabled assertions.")
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    parser.add_argument("--native",type=Path,default=FROZEN/"native")
    parser.add_argument("--compare",action="store_true")
    args=parser.parse_args()
    if args.compare and args.output.resolve()==FROZEN.resolve():
        sys.exit("Choose a separate replay directory.")
    run(args.output,args.native,args.compare)
