"""Force every port valuation through real queries. Enumerate SC orders independently."""
import itertools
import json
import subprocess
import sys
from pathlib import Path
import importlib.util
spec=importlib.util.spec_from_file_location("small",Path(__file__).with_name("pi1-small.py"))
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)


def main(binary,stock,out):
    out.mkdir(exist_ok=True,parents=True);summary={}
    W=("x#1","x","w"); W2=("x#3","x","w"); R=("x#2","x","r"); R2=("x#4","x","r")
    graphs={
        "triplet":s.model(nodes=[W,R,W2],edges=[("po",0,2,-1),("po",2,1,-1),("rf",0,1,0)],guards=[(0,-1),(2,2)]),
        "reverse":s.model(nodes=[W,R],edges=[("rf",0,1,1),("po",1,0,-1)],guards=[(0,2)]),
        "ws_fr":s.model(nodes=[W,W2,R,R2],edges=[("rf",0,2,0),("rf",1,3,2),("po",2,3,-1),("po",1,2,-1)],
                        guards=[(0,-1),(1,4)]),
        "atomic":s.model(nodes=[W,W2,R],edges=[("apo",0,2,-1),("rf",1,2,0),("po",0,1,-1)],
                         guards=[(0,-1),(1,2)]),
        "shared_negative_guard":s.model(nodes=[W,W2,R],edges=[("rf",0,2,2),("po",0,1,-1),("po",1,2,-1)],
                                         guards=[(0,1),(1,1)]),
        "dynamic_CO":s.model(nodes=[W,W2,R],edges=[("rf",0,2,0),("rf",1,2,2)],guards=[(0,4),(1,-1)],
                             b=[[1,3]]),
    }
    for name,m in graphs.items():
        d=out/name;d.mkdir(exist_ok=True);commands=[];expected=[];controls=[]
        for i,bits in enumerate(itertools.product((False,True),repeat=m["n"]),1):
            full=dict(m,id=i,a=[2*j+int(not val) for j,val in enumerate(bits)])
            expected.append("SAT" if s.allowed(full,bits) else "UNSAT")
            f=d/(str(i)+".txn");s.write(f,s.encode(full))
            r=subprocess.run([stock,f],capture_output=True,text=True,timeout=10)
            (d/(str(i)+".stock")).write_text(r.stdout+r.stderr)
            controls.append(r.stdout.split("STOCK ")[-1].strip() if r.returncode==0 else "FAILED")
            if i==1:commands.append(("APPEND",f))
            else:
                q=s.model(n=m["n"],a=full["a"],ident=i);qf=d/(str(i)+".query");s.write(qf,s.encode(q));commands.append(("QUERY",qf))
            commands.append(("SOLVE",i))
        proto=d/"protocol";proto.write_text("".join("\t".join(map(str,c))+"\n" for c in commands))
        proc=subprocess.run([binary,proto,d/"native.txt"],capture_output=True,text=True,timeout=20)
        (d/"output.txt").write_text(proc.stdout+proc.stderr)
        actual=[r["status"] for r in s.parse(proc.stdout)]
        entry=dict(expected=expected,stock=controls,actual=actual,returncode=proc.returncode)
        summary[name]=entry
        assert proc.returncode==0 and actual==expected,(name,entry,proc.stderr)
        assert controls==expected,(name,"stock",entry)
        data=(d/"native.txt").read_text().splitlines()
        mu=list(map(int,next(l for l in data if l.startswith("MU ")).split()[2:]))
        for line in data:
            if line.startswith("REASON "):s.inspect_reason(line,mu,m)
    (out/"checks.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(sum(len(v["actual"]) for v in summary.values()),"independent valuation/order and stock checks")
if __name__=="__main__":main(*(Path(x) for x in sys.argv[1:]))
