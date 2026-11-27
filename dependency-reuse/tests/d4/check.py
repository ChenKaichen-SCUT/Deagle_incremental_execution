"""Exercise the production selector and importer, with independent native births and finite P1 models."""
from collections import Counter
import argparse
import csv
import importlib.util
import itertools
import json
import struct
import subprocess
from pathlib import Path

HERE=Path(__file__).resolve().parent


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod


mixed=module("small_orders",HERE.parent/"d3/check.py")
cnf=module("small_cnf",HERE.parent/"d2/check.py")


def spec(z):
    lines=[f"{z.get('n',8)} 2 {int(z.get('stress',False))}"]
    lines += [" ".join(map(str,e)) for e in z["edges"]]
    lines += [f"guard {w} {g}" for w,g in z["guards"].items()]
    lines += [" ".join(map(str,[tag,*c])) for tag,c in bases(z)]
    lines.append("A "+" ".join(map(str,z["assumptions"])))
    return "\n".join(lines)+"\n"


def bases(z):
    return z.get("bases",[("B",c) for c in z["clauses"]])


def process(exe,src,argument,out):
    out.mkdir()
    with (out/"stdout").open("w") as log,(out/"stderr").open("w") as err:
        subprocess.run([exe,src,argument],cwd=out,stdout=log,stderr=err,check=True,timeout=60)
    return int(next(x.split()[-1] for x in (out/"stdout").read_text().splitlines() if x.startswith("fixture result ")))


def p0(tools,z,d):
    d.mkdir()
    (d/"spec").write_text(spec(z))
    for tag,binary in (("record","native"),("oracle","oracle")):
        process(tools/binary,d/"spec",d/tag/"proof.bin",d/tag)
    assert (d/"record/event-names.tsv").read_bytes()==(d/"oracle/event-names.tsv").read_bytes()
    return [(int(i),s,int(a)) for i,s,a in (l.split() for l in (d/"record/event-names.tsv").read_text().splitlines())]


def project(c,mapping):
    return tuple(sorted(set(mapping[abs(v)]^(v<0) for v in c)))


def write_delta(path,old,new,translation,ns):
    mixed.make_inputs(path,old,new,ns)
    seen=Counter((tag,tuple(sorted(set(map(cnf.raw,c))))) for tag,c in bases(new))
    raw=[];occ=[];counts=[];audit=[];mapping=[]
    for i,(tag,c) in enumerate(bases(old),1):
        original=list(map(cnf.raw,c))
        def fields(*args):return "\t".join(map(str,args))+"\n"
        keep=seen[tag,project(c,translation)] if all(abs(x) in translation for x in c) else 0
        raw.append(fields("C",tag,*original));occ.append(fields(0,i,tag,i,"matched" if keep else "missing"))
        counts.append(fields(i,tag,1,keep));audit.append(fields(tag,int(not keep),*original))
    for oldvar,newlit in translation.items():
        mapping.extend([fields(0,oldvar,newlit,"Atom","signed","symbol"),
                        fields(1,newlit//2,2*oldvar+(newlit&1),"Atom","signed","symbol")])
    for f,rows in (("model.tsv",raw),("occurrences.tsv",occ),("clause-counts.tsv",counts),("inputs",audit),("variables.tsv",mapping)):
        (path/f).write_text("".join(rows))
    (path/"map").write_text("".join(f"{k} {v}\n" for k,v in translation.items()))


def read_rows(path):
    with path.open() as f:return list(csv.DictReader(f,delimiter="\t"))


def delta(select,tools,old,new,p0_dir,out,ns,translation=None):
    out.mkdir()
    n=old.get("n",8);n1=new.get("n",8)
    mapping={i:i*2 for i in range(1,n+1)} if translation is None else translation
    write_delta(out,old,new,mapping,ns)
    proof=p0_dir/"record/proof.bin"
    subprocess.run([select,proof,out/"model.tsv",out,out/"decl",str(n+1),str(n1+1),out],check=True)
    subprocess.run([tools/"check",proof,out/"inputs",out/"map",p0_dir/"oracle/native-learns.tsv",out/"decl",out],check=True)
    native={int(r[0]):list(map(int,r[3:])) for r in (line.split() for line in (out/"selected.tsv").read_text().splitlines()[1:])}
    independently={int(r[0]):list(map(int,r[1:])) for r in (line.split() for line in (out/"survivors.tsv").read_text().splitlines())}
    assert native==independently
    kept=list(native.values())
    if "bases" not in new:models=mixed.exhaustive(new,kept)
    elif n1<=10:
        models=0
        for truth in itertools.product((False,True),repeat=n1):
            if all(any(truth[abs(v)-1]!=(v<0) for v in c) for tag,c in bases(new) if tag=="B"):
                models+=1
                assert all(any(truth[l//2-1]!=bool(l&1) for l in c) for c in kept)
    else:models=None  # full structural replay on the PHP stress case
    (out/"spec").write_text(spec(new))
    result=process(tools/"p1",out/"spec",out/"selected.tsv",out/"reuse")
    assert result==process(tools/"oracle",out/"spec",out/"cold/proof.bin",out/"cold")
    imports=read_rows(out/"reuse/imports.tsv")
    assert [int(r["id"]) for r in imports]==list(independently)
    metric=cnf.stats(out/"metrics.tsv")
    return dict(births=metric.get("births",0),selected=list(native),dispositions=Counter(r["disposition"] for r in imports),
                status=result,enumerated_models=models,reasons_retained=metric.get("theory_reasons_survive",0),
                evicted_parents=metric.get("used_parent_edges_to_evicted_learned",0),gc=metric.get("gc",0))


def minimization_witness(proof):
    data=proof.read_bytes();sections=[];at=12
    for stride in (16,4,8,16,12):
        num=struct.unpack_from("<I",data,at)[0];at+=4;sections.append((at,num));at+=stride*num
    nodes,lits,edges,inputs,learned=sections
    bases={struct.unpack_from("<I",data,inputs[0]+i*16)[0]:i for i in range(inputs[1])}
    closure=[set() for _ in range(nodes[1])]
    parents=[[] for _ in closure];lo=0
    for i in range(nodes[1]):
        _,hi,_,_=struct.unpack_from("<4I",data,nodes[0]+16*i)
        parents[i]=[struct.unpack_from("<I",data,edges[0]+8*j)[0] for j in range(lo,hi)]
        if i in bases:closure[i].add(bases[i])
        for p in parents[i]:closure[i].update(closure[p])
        lo=hi
    for j in range(learned[1]):
        i,u,m=struct.unpack_from("<3I",data,learned[0]+12*j)
        if not m:continue
        unique=set.union(set(),*(closure[p] for p in parents[i][u:u+m]))-set.union(
            set(),*(closure[p] for p in parents[i][:u]+parents[i][u+m:]))
        if unique:return i,min(unique)
    raise ValueError("expected a premise used only by minimization")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("select","tools","new_directory"):p.add_argument(arg,type=Path)
    a=p.parse_args();select,tools,root=[v.resolve() for v in (a.select,a.tools,a.new_directory)]
    root.mkdir(parents=True,exist_ok=False)
    results={}
    def group(name,old,changes):
        base=root/name;ns=p0(tools,old,base)
        for change,new,mapping in changes:
            results[name+"/"+change]=delta(select,tools,old,new,base,base/change,ns,mapping)
        return base
    for old,changes in ((mixed.direct,("same","B","T","B+T","unrelated")), (mixed.block,("same","merge","split")),
                        (mixed.compete,("same","guard","add-write")), (mixed.ws,("same","guard"))):
        group(old["tag"],old,[(ch,mixed.altered(old,ch),None) for ch in changes])
    def chosen(tag):return set(results[tag]["selected"])
    assert chosen("direct/same")==chosen("direct/unrelated")
    for ch in ("B","T","B+T"):assert not chosen("direct/"+ch) and chosen("direct/same")
    for ch in ("split","merge"):assert chosen("block/"+ch)<chosen("block/same")
    # Preserve an RF binding in a discharged conditional lemma, then weaken the guard it used.
    always=mixed.altered(mixed.compete,"same");always["guards"][mixed.X]=0
    group("true-guard",always,[("same",always,None),("conditional",mixed.compete,None)])
    assert results["true-guard/conditional"]["reasons_retained"]<results["true-guard/same"]["reasons_retained"]
    domain=mixed.benchmark("domain",[("rf",mixed.W,mixed.R,5),("rf",mixed.X,mixed.R,6),("po",mixed.R,mixed.W,0)])
    domain["clauses"]=[(5,6),(1,2,-6),(1,-2,-6),(7,3),(7,-3),(4,3),(4,-3)]
    expanded=mixed.altered(domain,"add-write");expanded["clauses"][0]=(5,6,8)
    group("domain",domain,[("same",domain,None),("expanded",expanded,None)])
    assert set()<chosen("domain/expanded")<chosen("domain/same")
    def boolean(n,rows,assum=(),stress=False):
        return dict(n=n,clauses=[],bases=list(rows),guards={},edges=[],assumptions=list(assum),stress=stress)
    clauses=[("B",c) for c in [(1,2),(1,-2),(3,4),(3,-4)]]
    sat=boolean(4,clauses)
    perm={1:7,2:8,3:2,4:5}
    def signed(v):
        raw=perm[abs(v)]^(v<0)
        return (-1 if raw&1 else 1)*(raw//2)
    renum=boolean(4,[(t,tuple(map(signed,c))) for t,c in reversed(clauses)])
    group("signed",sat,[("same",sat,None),("permuted",renum,perm),("missing",sat,{2:4,3:6,4:8})])
    assert chosen("signed/permuted")==chosen("signed/same") and chosen("signed/missing")<chosen("signed/same")
    gate=[("B",(-1,a,b)) for a in (2,-2) for b in (3,-3)]
    for t in ("Q","U"):
        z=boolean(3,[*gate,(t,(1,))])
        group(t,z,[("remove-and-change-query",boolean(3,gate,(-1,)),None)])
        assert results[t+"/remove-and-change-query"]["births"] and not chosen(t+"/remove-and-change-query")
    z=boolean(3,gate,(1,))
    group("assume",z,[("opposite",boolean(3,gate,(-1,)),None)])
    assert chosen("assume/opposite") and results["assume/opposite"]["status"]==10
    rootbase=[("B",c) for c in ((-1,2),(-2,9),(3,4,-9),(3,-4,-9),(1,),(-3,4,-9),(-3,-4,-9))]
    rootcase=boolean(9,rootbase)
    group("root-chain",rootcase,[("same",rootcase,None),("removed",boolean(9,rootbase[1:]),None)])
    assert chosen("root-chain/same") and not chosen("root-chain/removed")
    php=boolean(20,cnf.php(5),stress=True)
    base=group("minimize-gc",php,[("same",php,None)])
    birth,index=minimization_witness(base/"record/proof.bin")
    new=boolean(20,[c for j,c in enumerate(bases(php)) if j!=index],stress=True)
    results["minimize-gc/hidden-parent"]=delta(select,tools,php,new,base,base/"hidden-parent",[])
    z=results["minimize-gc/hidden-parent"]
    assert birth in chosen("minimize-gc/same") and birth not in z["selected"] and z["selected"] and z["evicted_parents"] and z["gc"]
    z.update(retired_birth=birth,removed_input=index+1)
    (root/"results.json").write_text(json.dumps(results,indent=2)+"\n")
    print(len(results),"production selector/importer cases passed")


if __name__=="__main__":main()
