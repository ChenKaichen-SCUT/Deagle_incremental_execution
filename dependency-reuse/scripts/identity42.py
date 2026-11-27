"""Controlled whole-model identity and renumbering, separate from automatic mapping."""
import argparse
import hashlib
import json
import random
import subprocess
from pathlib import Path
from d1_identity import Keys, Model, load_rows
from d41_identity import pair_sites
from diff_d1 import compare_theory, digest, one_var_table
from prepare_d3 import facts
from run_stock import BASE, save


def permute(model,dest,variables,events):
    """Rename native atoms in each typed table. Static source identities and term IDs are different namespaces."""
    unchanged={"DEAGLE-D1","K","S","SITE41","X","E","V","LAYOUT","V_LAYOUT","EVENT_LAYOUT","TERM","H",
               "VALUE_DEF","F","QUERY","TARGET","A_LAYOUT","END","READY"}
    def lit(raw):
        v=int(raw)
        if v in (-1,-2):return raw
        if v<2 or v//2 not in variables:raise ValueError(("outside signed permutation",v))
        return str(variables[v//2]^(v&1))
    def event(raw):return str(events[int(raw)]) if int(raw)>=0 else raw
    with model.open() as src,dest.open("x") as dst:
        for line in src:
            row=line.rstrip("\n").split("\t");tag=row[0]
            if tag in unchanged:dst.write(line);continue
            if tag in ("C","G","N"):p={"C":2,"G":2,"N":2}[tag];row[p:]=map(lit,row[p:])
            elif tag in ("A","GUARD"):row[-1]=lit(row[-1])
            elif tag=="NODE":row[1],row[-1]=event(row[1]),event(row[-1])
            elif tag in ("IN","OUT","MEMBER"):row[1:]=map(event,row[1:])
            elif tag=="EDGE":
                row[4]=lit(row[4]);row[5],row[6]=event(row[5]),event(row[6]);row[7]=lit(row[7])
            elif tag=="CO":
                row[1],row[2]=event(row[1]),event(row[2]);row[3:]=map(lit,row[3:])
            else:raise ValueError(("unrecognized typed row",tag))
            dst.write("\t".join(row)+"\n")


def run_one(model,lib,reference_facts,tools,case,out,signed,expected):
    out.mkdir(parents=True)
    size,events=0,[]
    with model.open() as f:
        for line in f:
            if line.startswith("N\t"):size=int(line.split()[1])
            if line.startswith("NODE\t"):events.append(int(line.split()[1]))
    rng=random.Random(420187)
    v=list(range(1,size));e=sorted(events)
    identity=signed is None
    if not identity:rng.shuffle(v);rng.shuffle(e)
    forward={i:2*j+(rng.getrandbits(1) if signed else 0) for i,j in enumerate(v,1)}
    emap=dict(zip(sorted(events),e));back={l//2:2*i+(l&1) for i,l in forward.items()}
    assert len(back)==size-1 and len(set(emap.values()))==len(events)
    target=model if identity else out/"renamed.tsv"
    if not identity:
        permute(model,target,forward,emap)
        permute(target,out/"inverse.tsv",back,{j:i for i,j in emap.items()})
        if digest(out/"inverse.tsv")!=digest(model):raise ValueError("whole interface or query not preserved")
        (out/"inverse.tsv").unlink()
    with (out/"variables.tsv").open("w") as f:
        for side,ids in enumerate((forward,back)):
            for a,b in ids.items():print(side,a,b,"Oracle","controlled",0,sep="\t",file=f)
    # Complete bijective transformation was checked on every typed row, not inferred from source identity.
    # The original declaration inventory is bound to the proof's exact old installed graph by select.
    with reference_facts.open() as f,(out/"declarations.txt").open("w") as w:
        for line in f:w.write(" ".join([*line.split()[:-1],"M"])+"\n" if line.startswith("D ") else line)
    subprocess.run([tools/"select",lib/"proof.bin",model,out,out/"declarations.txt",str(size),str(size),out,target],check=True)
    count=bad=0
    with (out/"catalog.tsv").open() as f:
        next(f)
        for line in f:
            id_,flags,has,alive,mapped,take=map(int,line.split())
            if bool(alive)!=not_bad(flags) or not mapped or take!=alive:raise ValueError(("control birth mismatch",case,id_))
            count+=take;bad+=not alive
    assert count==expected,(case,count,expected)
    if not identity:
        with (out.parent/"identity/selected.tsv").open() as orig,(out/"selected.tsv").open() as moved:
            assert orig.readline()==moved.readline()
            for left,right in zip(orig,moved):
                l,r=left.split(),right.split()
                assert l[:3]==r[:3] and [forward[int(s)//2]^(int(s)&1) for s in l[3:]]==list(map(int,r[3:]))
    return dict(proof_sha256=digest(lib/"proof.bin"),original=digest(model),fixture=digest(target),births=count+bad,
                eligible=count,rejected=bad,atoms=size-1,events=len(events),negative=sum(x&1 for x in forward.values()),
                signed_map_sha256=digest(out/"variables.tsv"),checked_inverse=True)


def not_bad(flags):return not(flags&7)


def hidden(model,target,archive,tools,out):
    out.mkdir(parents=True);keys=Keys();raw=[load_rows(model),load_rows(target)]
    pairs=pair_sites(*raw,keys)
    m=[Model(path,keys,True,records=r,site_pairs=p,recorded_queries=True) for path,r,p in zip((model,target),raw,pairs)]
    anchors=[out/"P0.anchors",out/"P1.anchors"]
    for i in (0,1):m[i].write_anchors(m[1-i],anchors[i])
    subprocess.run([tools/"boolean-diff",model,target,*anchors,out,"--d41-map-only"],check=True)
    maps,variables=one_var_table(out/"variables.tsv",m);old=[]
    compare_theory(m,maps,out,old_rows=old);facts(model,out,out/"declarations.txt",declaration_rows=old)
    subprocess.run([tools/"select",archive/"proof.bin",model,out,out/"declarations.txt",str(m[0].nvars),str(m[1].nvars),out,target],check=True)
    counts=[0,0,0]
    with (out/"catalog.tsv").open() as f:
        next(f)
        for line in f:
            _,flags,_,alive,mappable,take=map(int,line.split())
            counts[0]+=mappable;counts[1]+=take;counts[2]+=not_bad(flags)
    return dict(vars=variables,final_mappable=counts[0],eligible=counts[1],permanent=counts[2])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ("d41_matrix","d41_audit","tools","output"):p.add_argument(n,type=Path)
    a=p.parse_args();root=a.output.resolve();root.mkdir(parents=True)
    plan=json.loads((BASE/"configs/d42-plan.json").read_text());summary={}
    for case,expected in zip(plan["cases"],plan["permanent_controls"]):
        lib=a.d41_matrix/case/"compact/P0/native";model=lib/"model.tsv"
        receipt=json.loads((lib/"receipt.json").read_text());assert all(digest(lib/f)==h for f,h in receipt["library_sha256"].items())
        decl=a.d41_audit/case/"self-d41/delta/declarations.txt"
        one=summary[case]={}
        for label,sign in (("identity",None),("unsigned",False),("signed",True)):
            one[label]=run_one(model,lib,decl,a.tools,case,root/case/label,sign,expected)
        one["hidden_d41"]=hidden(model,root/case/"signed/renamed.tsv",lib,a.tools,root/case/"hidden-d41")
        save(root/"identity-controls.json",summary);print("controlled transport",case,expected,flush=True)


if __name__=="__main__":main()
