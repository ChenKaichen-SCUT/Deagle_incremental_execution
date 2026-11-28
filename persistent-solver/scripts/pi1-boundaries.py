"""Exercise transactional rejection, query extension, interruption, signed aliases and audit mutations."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

def module(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+".py"))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

small=module("pi1-small")


def run(binary,out):
    out.mkdir(exist_ok=True,parents=True)
    base=small.model(n=2,b=[[0]])
    def stage(name,m,rows=None):
        path=out/(name+".txn");small.write(path,small.encode(m) if rows is None else rows);return str(path)
    first=stage("base",base);base["_seal"]=Path(first+".sha256").read_text().strip()
    same=stage("same",base,small.encode(base,base))
    q=small.model(n=3,ident=2,q=[[4]],a=[5]);q["extra"]=[("NEWATOM",2)]
    second=stage("extension",q)
    broken=stage("broken",base);p=Path(broken);p.write_bytes(p.read_bytes()[:-2])
    badscope=small.model(n=2,b=[[4]])
    wrong=stage("space",badscope)
    badmap=dict(base,map=[(0,0),(1,1)])
    duplicate=stage("noninjective",badmap,small.encode(badmap,base))
    malformed=small.model(nodes=[("x#1","x","w"),("x#2","x","r")],edges=[("rf",0,1,0)])
    badDomain=stage("domain",malformed,[("DOMAIN",1) if r[0]=="DOMAIN" else r for r in small.encode(malformed,base)])
    forged=stage("unrelated_predecessor",base,[("BASE","0"*64) if r[0]=="BASE" else r for r in small.encode(base,base)])
    commands=[("APPEND",first),("REJECT",same),("SOLVE",1),("REJECT",broken),("REJECT",wrong),("REJECT",duplicate),("REJECT",forged),
              ("REJECT",badDomain),("QUERY",second),("SOLVE",2),("SOLVE",1),("INTERRUPT",),("SOLVE",1),
              ("RESUME",),("APPEND",same),("SOLVE",1),("GC",),("SOLVE",1)]
    proto=out/"protocol";proto.write_text("".join("\t".join(map(str,c))+"\n" for c in commands))
    proc=subprocess.run([binary,proto,out/"actual.txt"],capture_output=True,text=True,timeout=10)
    (out/"output.txt").write_text(proc.stdout+proc.stderr)
    assert proc.returncode==0,proc.stderr
    rows=small.parse(proc.stdout);statuses=[r["status"] for r in rows]
    assert statuses==["SAT","UNSAT","SAT","UNKNOWN","SAT","SAT"] and len(rows[2]["assignment"])==2
    rejects=[l for l in proc.stdout.splitlines() if l.startswith("REJECTED ")]
    assert len(rejects)==6
    # Corrupt real allocator output in the verifier, independently of the model runner.
    directory=out.parent/"small"/"reverse_rf_delete_po"
    lines=(directory/"native.txt").read_text().splitlines()
    reason=next(l for l in lines if l.startswith("REASON "))
    mu=list(map(int,next(l for l in lines if l.startswith("MU ")).split()[2:]))
    m=small.examples()["reverse_rf_delete_po"][0]
    prefix,raw=reason.split(" |");f=prefix.split()
    failures=[]
    for name,change in [("drop_epoch"," ".join(f[:-1])+" |"+raw),
                        ("wrong_polarity"," ".join(f[:7]+[str(int(f[7].split("/")[0])^1)+"/3/0"]+f[8:])+" |"+raw),
                        ("nonfalse_antecedent",prefix.replace("/1/1","/0/1")+" |"+raw)]:
        try:small.inspect_reason(change,mu,m)
        except AssertionError:failures.append(name)
    assert len(failures)==3
    delayed={}
    nodes=[("x#1","x","w"),("x#2","x","r")]
    for kind,badgraph in (("cycle",[("po",0,1,-1),("po",1,0,-1)]),
                           ("unit",[("rf",0,1,0),("po",1,0,-1)])):
        ms=[small.model(nodes=nodes,edges=g,guards=[(0,-1)]) for g in (badgraph,badgraph[:1] if kind=="unit" else [],badgraph)]
        paths=[];previous=None
        for i,m in enumerate(ms):
            f=out/(kind+str(i)+".txn");small.write(f,small.encode(m,previous));m["_seal"]=Path(str(f)+".sha256").read_text().strip()
            paths.append(str(f));previous=m
        cmd=[("INTERRUPT",),("APPEND",paths[0]),("SOLVE",1),("RESUME",),("APPEND",paths[1]),("SOLVE",1),("APPEND",paths[2]),("SOLVE",1)]
        steps=out/(kind+".protocol");steps.write_text("".join("\t".join(map(str,c))+"\n" for c in cmd))
        rr=subprocess.run([binary,steps,out/(kind+".native")],capture_output=True,text=True,timeout=10)
        (out/(kind+".output")).write_text(rr.stdout+rr.stderr)
        actual=small.parse(rr.stdout);assert rr.returncode==0 and len(actual)==3,(kind,rr.stderr)
        assert [r["status"] for r in actual]==["UNKNOWN","SAT","UNSAT" if kind=="cycle" else "SAT"]
        native=actual[-1]["native"]
        if kind=="cycle":assert native["delayed_conflicts"]==1
        else:assert native["rebuilds"]>=2 and native["theory_props"]>=1
        delayed[kind]=native
    probes={}
    for label,m in (("false_control",small.model(b=[[],[0],[2]])),
                    ("graph_conflict",small.model(nodes=nodes,edges=[("po",0,1,-1),("po",1,0,-1)],b=[[0]]))):
        f=out/(label+".txn");small.write(f,small.encode(m))
        steps=out/(label+".protocol");steps.write_text(f"APPEND\t{f}\nPROBE\t1\n")
        rr=subprocess.run([binary,steps],capture_output=True,text=True,timeout=10)
        (out/(label+".output")).write_text(rr.stdout+rr.stderr)
        row=small.parse(rr.stdout)[0];mtr=row["native"]
        assert rr.returncode==0 and row["status"]=="DIAGNOSTIC" and mtr["decisions"]==0
        assert mtr["boundary_status"] in ("BOUNDARY_FALSE_ASSUMPTION","BOUNDARY_CONFLICT") and mtr["prefix"]<mtr["assumptions"]
        probes[label]={"checked":mtr["prefix"],"total":mtr["assumptions"],"status":mtr["boundary_status"]}
    d=dict(statuses=statuses,rejections=rejects,allocator_faults_rejected=failures,delayed=delayed,partial_probes=probes)
    (out/"checks.json").write_text(json.dumps(d,indent=2)+"\n")
    return d

if __name__=="__main__":
    print(run(Path(sys.argv[1]),Path(sys.argv[2])))
