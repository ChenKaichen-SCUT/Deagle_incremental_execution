"""Read native trail, CRef clause contents, five Closure scopes and actual graph edges across restart."""
import itertools
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

small=runpy.run_path(str(Path(__file__).with_name("pi1-small.py")))
model,encode,write=map(small.get,("model","encode","write"))


def split(value):
    return [x for x in value.rstrip(",").split(",") if x]


def state(line):
    _,kind,version,target,A,gen,floor,depth,qhead,cursor,installed,epoch,*fields=line.split()
    s=dict(zip(("version","target","A","gen","floor","depth","qhead","cursor","installed","epoch"),
               map(int,(version,target,A,gen,floor,depth,qhead,cursor,installed,epoch))))
    for item in fields:
        name,value=item.split("=")
        if name=="pending":s[name]=list(map(int,value.split("/")))
        else:s[name]=[tuple(map(int,x.split("/"))) for x in split(value)]
    s["kind"]=kind
    return s


def projection(before,after,assume):
    a=before["A"]
    assert before["target"]==after["target"]==after["depth"]==a==before["installed"]==after["installed"]==len(assume)
    assert before["gen"]==after["gen"] and before["floor"]==after["floor"]<=a
    assert after["limits"]==before["limits"][:a]
    cut=len(before["trail"]) if len(before["limits"])==a else before["limits"][a][0]
    assert after["trail"]==before["trail"][:cut]
    for snap in (before,after):
        assert snap["qhead"]==snap["cursor"]==len(snap["trail"]) and not any(snap["pending"])
        seen={}
        for pos,(p,level,ref,*clause) in enumerate(snap["trail"]):
            if ref!=4294967295:
                assert clause[0]==p and all((v^1) in seen for v in clause[1:]),(snap["kind"],p,clause)
            seen[p]=level
        assert all(p in seen and seen[p]<=i+1 for i,p in enumerate(assume))
        assert snap["epoch"] in seen
        for edge in snap["edges"]:
            assert all(p<0 or p in seen for p in edge[2:])
        assert all(g<0 or g in seen for _,g in snap["guards"])
    for key in ("edge","rf","guard","vital","triplet"):
        assert after[key]==before[key][:a+1]
    for key in ("edges","rfs","guards","vitals","triplets"):
        assert set(after[key])<=set(before[key])
    return {"A":a,"removed_assignments":len(before["trail"])-cut,
            "removed_edges":sorted(set(before["edges"])-set(after["edges"])),
            "kept_edges":after["edges"],"kept_guards":after["guards"],
            "dummy":any(after["limits"][i][0]==(after["limits"][i+1][0] if i+1<a else cut) for i in range(a)),
            "retained_reasons":sum(t[2]!=4294967295 for t in after["trail"])}


def main(binary,stock,out):
    out.mkdir(parents=True,exist_ok=True)
    x=[("x#1","x","w"),("x#2","x","r")]
    ordinary=model(n=6,b=[[0,8,6],[0,8,7]],nodes=x+[("y#1","y","w"),("y#2","y","r")],
                   edges=[("rf",0,1,1),("rf",2,3,2)],guards=[(0,-1),(2,4)],a=[2,4,-1])
    cond=model(n=5,b=[[2,6],[2,7],[3,6]],nodes=x+[("x#3","x","w")],
               edges=[("rf",0,1,0),("po",0,2,-1),("po",2,1,-1)],guards=[(0,-1),(2,4)],a=[4,-1])
    co=model(n=4,b=[[2,4],[2,5],[3,4]],nodes=[x[0],("x#3","x","w")],guards=[(0,-1),(1,-1)])
    core=model(b=[[1,3,4],[1,3,5]],a=[0,2])
    cases={"rf_projection":ordinary,"guard_propagation":cond,"failed_prefix":core,"restart_co":co,
           "budget":ordinary,"after_collection":ordinary}
    trip_nodes=[x[0],("x#3","x","w"),x[1]]
    for name,last in (("triplet_pruned",("rf",1,2,1)),("triplet_retained",("po",1,2,-1))):
        cases[name]=model(n=6,b=[[0,8,6],[0,8,7]],nodes=trip_nodes,
                          edges=[("po",0,1,-1),("rf",0,2,2),last],guards=[(0,-1),(1,4)],a=[-1])
    report={}
    for name,m in cases.items():
        d=out/name;d.mkdir(exist_ok=True)
        t=d/"model";write(t,encode(m));protocol=d/"protocol"
        lines=["RESTART\t1","APPEND\t"+str(t)]
        if name=="budget":
            lines.insert(1,"BUDGET\t1")
            lines+=["SOLVE\t1","BUDGET\t-1"]
        if name=="after_collection":lines+=["INTERRUPT","SOLVE\t1","RESUME","GC"]
        protocol.write_text("\n".join(lines+["SOLVE\t1"])+"\n")
        p=subprocess.run([binary,protocol,d/"native"],capture_output=True,text=True,timeout=15)
        (d/"out").write_text(p.stdout+p.stderr)
        assert p.returncode==0,(name,p.stderr)
        rr=small["parse"](p.stdout); r=rr[-1]; native=r["native"]
        expected=any(small["allowed"](m,bits) for bits in itertools.product((False,True),repeat=m["n"]))
        ref=subprocess.run([stock,t],capture_output=True,text=True,timeout=15)
        (d/"stock").write_text(ref.stdout+ref.stderr)
        assert ref.returncode==0 and "STOCK "+r["status"] in ref.stdout and (r["status"]=="SAT")==expected
        if expected:assert small["allowed"](m,tuple(c=="1" for c in r["assignment"]))
        raw=(d/"native").read_text().splitlines()
        mu=list(map(int,next(l for l in raw if l.startswith("MU ")).split()[2:]))
        assume=list(map(int,next(l for l in raw if l.startswith("ASSUME ")).split()[3:]))
        for l in raw:
            if l.startswith("REASON "):small["inspect_reason"](l,mu,m)
        states=[state(l) for l in raw if l.startswith("STATE ")]
        projections=[projection(s,states[i+1],assume) for i,s in enumerate(states) if s["kind"]=="restart" and s["target"]]
        optimized=os.environ.get("PI1R_MODE")!="R0"
        if name=="rf_projection" and optimized:
            assert any(s["removed_edges"] and s["kept_edges"] and s["kept_guards"] and s["removed_assignments"] for s in projections)
            assert native["empty"]>0 and any(p["dummy"] for p in projections)
            assert any(l.startswith("STATE after") and ("2/3/"+str(mu[1])) in l for l in raw)
        if name.startswith("triplet_") and optimized:
            i=next(i for i,s in enumerate(states) if s["kind"]=="restart" and s["target"])
            before,after=states[i:i+2]
            triplet=(0,1,2,mu[1],mu[2])
            assert triplet in before["triplets"] and (triplet in after["triplets"])==(name=="triplet_retained")
        if name=="failed_prefix":
            assert r["native_failed_assumptions"] and native["restart_study"]["prefix_jumps"][0]>0
            assert any(s["kind"]=="uip" and 0<s["target"]<s["A"] for s in states)
            assert any(s["kind"]=="failed" for s in states)
        if name=="restart_co":
            index=next(i for i,l in enumerate(raw) if l.startswith("CO "))
            assert any(l.startswith("STATE after") for l in raw[:index])
        if name=="guard_propagation":
            assert any(l.startswith("REASON ") and str(mu[2]^1) in l.partition(" |")[2].split() for l in raw)
        if name=="budget":
            assert rr[0]["status"]=="UNKNOWN" and rr[0]["native"]["restart_study"]["budget_exit"]==1
            assert any(s["kind"]=="budget" and s["depth"]>0 for s in states)
        if name=="after_collection":
            assert native["collections"] and native["reductions"] and native["restart_study"]["ordinary"]
        for q in rr:
            assert q["native"]["pushes"]==q["native"]["pops"] and q["solver_construct_count"]==1
            z=q["native"]["restart_study"];assert z["end_level"]==z["end_graph"]==0
        report[name]={"status":[q["status"] for q in rr],"projections":projections,"native":native}
    # Existing three-version delayed-cycle fixture actually normalizes inside A, then crosses its activation barrier.
    late=[state(l) for l in (out.parent/"boundaries/cycle.native").read_text().splitlines() if l.startswith("STATE ")]
    assert any(s["kind"]=="late" and 0<s["target"]<s["A"] for s in late)
    assert any(s["kind"]=="late" and s["target"]<s["floor"] for s in late)
    replay=small["parse"]((out.parent/"boundaries/unit.output").read_text())[-1]["native"]
    assert replay["rebuilds"]>=2 and replay["replay"]==replay["rebuilds"]
    if os.environ.get("PI1R_MODE")!="R0":
        # This example retains a real allocated theory reason (not just decision literals).
        raw=(out.parent/"small/restart_theory_replay/native.txt").read_text().splitlines()
        pos=next(i for i,l in enumerate(raw) if l.startswith("STATE restart "))
        a,b=map(state,raw[pos:pos+2])
        args=list(map(int,next(l for l in raw if l.startswith("ASSUME ")).split()[3:]))
        actual=projection(a,b,args)
        reasons=[int(l.split()[1]) for l in raw[:pos] if l.startswith("ENQUEUE ")]
        assert any(t[2] in reasons for t in b["trail"])
        import copy
        faults=[]
        for kind in ("CRef","guard_scope","cursor"):
            damaged=copy.deepcopy(b)
            if kind=="CRef":
                i=next(i for i,t in enumerate(b["trail"]) if t[2] in reasons)
                t=b["trail"][i];damaged["trail"][i]=t[:2]+(4294967295,)+t[3:]
            elif kind=="guard_scope":damaged["guard"][-1]=(10000,)
            else:damaged["cursor"]-=1
            try:projection(a,damaged,args)
            except AssertionError:faults.append(kind)
        assert len(faults)==3
        report["retained_theory_CRef"]={"projection":actual,"rejected_corruptions":faults}
    (out/"checks.json").write_text(json.dumps(report,indent=2)+"\n")
    print("PASS",len(report),"native restart controls")

if __name__=="__main__":main(*(Path(x) for x in sys.argv[1:]))
