"""Real grouped native searches, finite Boolean/order oracle, kept and retired native clauses, and corrupted journals."""
import itertools
import json
import os
from pathlib import Path
import runpy
import struct
import subprocess
import sys

here=Path(__file__).resolve().parent
s=runpy.run_path(str(here/"pi1-small.py"))
audit=runpy.run_path(str(here/"pi1g-audit.py"))
model=s["model"];FINE,GP,RESET=audit["scale"]["PLAN"]["arms"]


def control(binary,stock,d,mode,models,extra_query=None):
    d.mkdir(parents=True)
    cmds=[];previous=None;paths={};sequence=[]
    env=dict(os.environ,PI1R_MODE="R2",PI1G_MODE=mode,PI1G_AUDIT=str(d/"input.bin"),PI1_ASSUMPTION_FILE=str(d/"args.bin"))
    env.pop("PI1R_LEDGER",None);env.pop("PI1R_DATABASE",None)
    for i,m in enumerate(models,1):
        p=d/(str(i)+".txn");s["write"](p,s["encode"](m,previous));m["_seal"]=Path(str(p)+".sha256").read_text().strip()
        paths[i]={0:p,m["id"]:p};cmds.extend([("APPEND",p),("SOLVE",m["id"])]);sequence.append(m)
        if extra_query and i==1:
            q=extra_query;qp=d/"extra.txn";s["write"](qp,s["encode"](q));paths[i][q["id"]]=qp
            cmds.extend([("QUERY",qp),("SOLVE",q["id"]),("SOLVE",m["id"])])
            sequence.extend([dict(m,q=q["q"],a=q["a"],id=q["id"]),m])
        previous=m
    protocol=d/"protocol";protocol.write_text("".join("\t".join(map(str,row))+"\n" for row in cmds))
    proc=subprocess.run([binary,protocol,d/"native.txt"],env=env,capture_output=True,text=True,timeout=20)
    (d/"stdout").write_text(proc.stdout+proc.stderr);assert proc.returncode==0,proc.stderr
    rr=s["parse"](proc.stdout);assert len(rr)==len(sequence)
    for i,(r,m) in enumerate(zip(rr,sequence)):
        expected=any(s["allowed"](m,val) for val in itertools.product((False,True),repeat=m["n"]))
        exact=d/("stock"+str(i)+".txn");s["write"](exact,s["encode"](m))
        baseline=subprocess.run([stock,exact],capture_output=True,text=True,timeout=15)
        (d/("stock"+str(i)+".out")).write_text(baseline.stdout+baseline.stderr)
        assert r["status"]==("SAT" if expected else "UNSAT") and baseline.returncode==0 and "STOCK "+r["status"] in baseline.stdout
        if expected:
            bits=tuple(c=="1" for c in r["assignment"]);assert s["allowed"](m,bits)
            assert any(all(r["order"][m["nodes"][i][0]]<=r["order"][m["nodes"][j][0]] for i in order for j in order if order[i]<order[j])
                       for order in s["orders"](m,bits))
        assert r["solver_construct_count"]==(r["version"] if mode==RESET else 1)
        assert all(r[k]==0 for k in ("old_learnt_import_count","old_learnt_export_count","per_clause_reproof_count"))
    receipts,layouts=audit["verify"](d/"input.bin",d/"args.bin",paths,mode,rr)
    return rr,receipts,layouts,paths


def faults(d,paths,mode,rows):
    journal=list(audit["records"](d/"input.bin"));raw=(d/"args.bin").read_bytes()
    groups=[f[1] for k,f in journal if k==3 and f[3]==-1];old=groups[0]
    one=next(f for k,f in journal if k==4 and f[1]==old)
    def run(name,records,controls):
        bad=d/(name+".bin");bad.write_bytes(b"".join(struct.pack("<"+"i"*(len(f)+2),k,len(f),*f) for k,f in records))
        act=d/(name+".args");act.write_bytes(controls)
        try:audit["verify"](bad,act,paths,mode,rows)
        except (ValueError,KeyError) as e:return str(e)
        raise AssertionError("fault accepted: "+name)
    missing=journal[:];del missing[next(i for i,(k,f) in enumerate(missing) if k==4 and f==one)]
    mutated=journal[:];at=next(i for i,(k,f) in enumerate(mutated) if k==1 and f[0]==2)+1
    mutated.insert(at,(4,one[:-1]+(one[-1]^1,)))
    changed=bytearray(raw);offset=16+struct.unpack_from("<4I",raw,0)[2]*4
    n=struct.unpack_from("<4I",raw,offset)[2]
    vals=struct.unpack_from("<"+"I"*n,raw,offset+16)
    ix=vals.index(old*2+1);struct.pack_into("<I",changed,offset+16+ix*4,old*2)
    return {"missing_member":run("omit",missing,raw),"rebound_payload":run("rebind",mutated,raw),"partial_enabled":run("partial",journal,changed)}


def main(binary,stock,out):
    out.mkdir(parents=True,exist_ok=True);simple=model(b=[[0,2],[0,3]])
    many=[[0]+[2*(i+1)+(v==2) for i,v in enumerate(comb) if v]
          for comb in itertools.product(range(3),repeat=6) if any(comb)][:260]
    cases={"survive":[simple,model(b=[[0,3],[0,2],[0,2]])],
           "retire":[simple,model(b=[[0,2]],a=[1]),model(b=[[0,2],[0,3]])],
           "replace":[simple,model(b=[[0,2],[0,4]],a=[1])],
           "width_reorder":[model(n=7,b=many),model(n=7,b=list(reversed(many[1:]))+[many[80]])],
           "empty_units":[model(b=[]),model(b=[[],[],[-1],[0,1]]),model(b=[[0],[-2,0]],a=[1]),model(b=[])],
           "query_switch":[model(b=[[0,2]],q=[],a=[-1]),model(b=[[0,2]],q=[[2]])],
           "signed":[model(b=[[0,2],[1,4]]),dict(model(b=[[3,0],[2,4]]),map=[(0,3),(1,0),(2,4)])]}
    outdata={};layouts={};hit=None
    for mode in (GP,RESET):
        outdata[mode]={}
        for name,models in cases.items():
            folder=out/mode/name
            rr,ch,layout,paths=control(binary,stock,folder,mode,models,model(q=[[]],ident=2) if name=="query_switch" else None)
            v={"status":[r["status"] for r in rr],"inputs":ch,"families":[r["native"]["families"] for r in rr]}
            if name=="retire" and mode==GP:
                v["faults"]=faults(folder,paths,mode,rr)
                old=[l.split() for l in (folder/"native.txt").read_text().splitlines() if l.startswith("OLDCLAUSE 2 ")]
                off={l for l in next(it for it in audit["signed"](folder/"args.bin") if it[0]==2)[3] if l&1}
                assert any(f[4]=="1" and off.intersection(map(int,f[5:])) for f in old)
                assert rr[1]["assignment"][0]=="0"
            if name=="survive" and mode==GP:
                lines=(folder/"native.txt").read_text().splitlines()
                old={int(w[2]):w for l in lines if l.startswith("OLDCLAUSE 2 ") for w in [l.split()] if w[4]=="0"}
                hit=next((l for l in lines if l.startswith("USE 2 1 ") and int(l.split()[3]) in old and l.split()[4] in ("0","2")),None)
                assert hit,lines;v["actual_hit"]=[old[int(hit.split()[3])],hit]
            if mode==GP:layouts[name]=layout
            else:
                # Reset is the registered P0/P1 control. Later small versions test formula semantics
                # and persistent reactivation after an intervening deletion.
                assert all(a==b for r,a,b in zip(rr,layouts[name],layout) if r["version"]<=2),(mode,name)
                v["partition_matches_persistent"]=[a==b for a,b in zip(layouts[name],layout)]
            outdata[mode][name]=v
    # Exercise the original theory/Boolean examples under grouped activation as well.
    for name,ms in s["examples"]().items():
        rr,_,_,_=control(binary,stock,out/"grouped-core"/name,GP,ms)
        outdata.setdefault("grouped-core",{})[name]=[r["status"] for r in rr]
    (out/"checks.json").write_text(json.dumps(outdata,indent=2)+"\n")
    print("PASS",len(cases),"group sequences / arm,",len(s["examples"]()),"inherited sequences,",hit)

if __name__=="__main__":main(*(Path(i) for i in sys.argv[1:]))
