"""Replay full native proofs, compare the compact slice and audit proof-relevant mappings."""
import argparse
from collections import Counter, defaultdict
import csv
import json
import hashlib
import mmap
from pathlib import Path
import struct
import subprocess


from audit_d4 import delta_inputs, numbers, rows, sample, unpack
from d1_identity import Keys, Model, load_rows
from d3_mapping import audit_gates
from d41_identity import pair_sites
from diff_d1 import compare_theory, one_var_table
from package_d1 import packed
from prepare_d3 import facts
from run_stock import BASE, save
from verify_d3_boundary import verify


def lines(path):
    with path.open() as f:
        for line in f:yield line.split()


def witnesses(path):
    """Sparse native input ordinals selected by independently verified reachability projection."""
    with path.open("rb") as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data:
        assert data[:6]==b"DEAGDC"
        at=12
        for width in (16,4,8):
            count=struct.unpack_from("<I",data,at)[0];at+=4+width*count
        count=struct.unpack_from("<I",data,at)[0];at+=4
        return {struct.unpack_from("<4I",data,at+16*i)[3] for i in range(count)}


def native_digest(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for row in f:
            if row.startswith((b"C\t",b"G\t",b"N\t",b"NODE\t",b"EDGE\t",b"GUARD\t",b"IN\t",b"OUT\t",b"MEMBER\t")):h.update(row)
    return h.hexdigest()


def self_delta(model,tool,out,improved):
    dest=out/"delta";dest.mkdir(parents=True)
    src=[load_rows(model),load_rows(model)]
    keys=Keys();pairs=pair_sites(*src,keys) if improved else (None,None)
    m=[Model(model,keys,True,records=s,recorded_queries=True,site_pairs=p) for s,p in zip(src,pairs)]
    anchors=[dest/"P0.anchors",dest/"P1.anchors"]
    for i in (0,1):m[i].write_anchors(m[1-i],anchors[i])
    subprocess.run([tool,model,model,*anchors,dest,"--d41-map" if improved else "--d4-boundary"],check=True)
    maps,variables=one_var_table(dest/"variables.tsv",m)
    compare_theory(m,maps,dest);facts(model,dest,dest/"declarations.txt")
    save(out/"delta.json",dict(variables=variables))


def map_audit(old,peer,delta,oracle,used,required,out):
    """Reconstruct matched permanent Boolean inputs directly in signed P1 literal space."""
    variables={}
    for side,v,to,role,why,_ in lines(delta/"variables.tsv"):
        if side!="0":break
        variables[int(v)]=(int(to),role,why)
    def missing(raw):
        v=raw//2
        return raw not in (-2,-1) and (v not in variables or variables[v][0]<0)
    def key(lits):return tuple(sorted(set(lits)))
    p1=set()
    with peer.open() as f:
        for l in f:
            if l.startswith("C\tB\t") or l=="C\tB\n":p1.add(key(map(int,l.split()[2:])))
    counted={int(i) for i,s,a,b in lines(delta/"clause-counts.tsv") if s=="B" and int(b)}
    buckets=defaultdict(Counter);examples={};leaf_roles=Counter()
    with old.open() as f,(out/"proof-inputs.tsv").open("w") as tab:
        print("ordinal\tin_any_birth\tin_permanent_birth\tstate\tfirst_unmapped_signed_literal",file=tab)
        clauses=(l for l in f if l.startswith("C\t"))
        for i,(l,row) in enumerate(zip(clauses,lines(delta/"occurrences.tsv")),1):
            side,ord_,scope,ref,_=row
            assert side=="0" and int(ord_)==i and l.split()[1]==scope
            if scope!="B":continue
            literals=list(map(int,l.split()[2:]))
            bad=[v for v in literals if missing(v)]
            match=not bad and key(v if v in (-2,-1) else variables[v//2][0]^(v&1) for v in literals) in p1
            assert bool(match)==(int(ref) in counted),(i,scope,"signed independent premise")
            state="unmapped" if bad else "matched" if match else "mapped_absent"
            for group,pick in (("all",True),("any_birth",i in used),("permanent_birth",i in required)):
                if pick:buckets[group][state]+=1
            if i in used or i in required:
                print(i,int(i in used),int(i in required),state,bad[0] if bad else "-",sep="\t",file=tab)
                for v in bad:leaf_roles[variables[v//2][1]]+=1
                if state!="matched" and state not in examples:examples[state]=dict(ordinal=i,literals=literals,first_unbound=bad[:1])
    blocked=Counter();reason_counts=Counter();mapped=[];first={}
    for j,(_, *c) in enumerate((r for r in lines(oracle) if r[0]=="L"),1):
        absent={int(v)//2 for v in c if missing(int(v))}
        if not absent:mapped.append(j);continue
        for role in {variables[v][1] for v in absent}:blocked[role]+=1
        for why in {variables[v][2].split(":")[0] for v in absent}:reason_counts[why]+=1
        for v in sorted(absent):
            to,role,why=variables[v]
            if role not in first:first[role]=dict(birth_ordinal=j,signed_clause=c,variable=v,reason=why)
    blocked_vars={v["variable"] for v in first.values()}
    with old.open() as f:
        for l in f:
            cells=l.split()
            if not cells:continue
            if cells[0]=="G" and int(cells[2])//2 in blocked_vars:
                v=int(cells[2])//2
                first[variables[v][1]]["definition"]=cells[1:]
            elif cells[0]=="A" and int(cells[-1])//2 in blocked_vars:
                v=int(cells[-1])//2
                first[variables[v][1]].setdefault("semantic_atoms",[]).append(cells[1:])
    packed(delta/"variables.tsv",out/"variables.tsv.gz")
    return dict(matched_variables=sum(t>=0 for t,_,_ in variables.values()),old_variables=len(variables),
                gate_definitions_checked=audit_gates(out,old,peer),premises=buckets,example_premises=examples,
                final_mapped=len(mapped),mapped_birth_ordinal_sample=mapped[:8],
                blocked_births_by_role=blocked,blocked_births_by_reason=reason_counts,
                blocked_literal_occurrences_on_used_premises=leaf_roles,first_failed_conclusions=first)


def retired_examples(old,run,out):
    """One shortest dependency path per missing leaf type on the first two translatable retired mixed births."""
    from collections import deque
    selected=[(j,int(r[0])) for j,r in enumerate(lines(out/"AB/learned.tsv"),1) if r[12]=="1" and r[7:9]==["0","1"]][:2]
    with old.open("rb") as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data:
        pos=12;sections=[]
        for width in (16,4,8,16,12,8,12,4,4,4,4,4,20):
            n=struct.unpack_from("<I",data,pos)[0];sections.append((pos+4,n,width));pos+=4+n*width
        def lookup(section,node):
            at,count,width=sections[section];lo,hi=0,count
            while lo<hi:
                m=(lo+hi)//2;v=struct.unpack_from("<I",data,at+width*m)[0]
                if v<node:lo=m+1
                else:hi=m
            assert lo<count and struct.unpack_from("<I",data,at+width*lo)[0]==node
            return lo,at+width*lo
        with (out/"proof-inputs.tsv").open() as h:
            causes={int(r["ordinal"]):r["state"] for r in csv.DictReader(h,delimiter="\t")}
        decls={tuple(map(int,r[1:5])):r[5] for r in lines(run/"delta/declarations.txt") if r[0]=="D"}
        found={}
        for ordinal,target in selected:
            queue=deque([target]);child={target:None};examples={}
            while queue:
                i=queue.popleft();nodes,_,_=sections[0];lits,_,_=sections[1];edges,_,_=sections[2]
                lo,start=struct.unpack_from("<II",data,nodes+16*(i-1))
                hi,end,kind,_=struct.unpack_from("<IIII",data,nodes+16*i)
                why=None;entry={}
                if kind==1:
                    number=lookup(3,i)[0]+1
                    if causes[number]!="matched":
                        why=causes[number];entry=dict(input_ordinal=number,signed_clause=list(struct.unpack_from("<"+"i"*(hi-lo),data,lits+4*lo)))
                elif kind==12:
                    _,op,a,b,c=struct.unpack_from("<IIiii",data,lookup(12,i)[1]);status=decls[op,a,b,c]
                    if status!="M":why="declaration_"+status;entry=dict(rule=[op,a,b,c])
                if why and why not in examples:
                    path=[];node=i
                    while node is not None:path.append(node);node=child[node]
                    examples[why]=dict(path_birth_to_seed=path[::-1],**entry)
                for j in range(start,end):
                    parent=struct.unpack_from("<I",data,edges+8*j)[0]
                    if parent not in child:child[parent]=i;queue.append(parent)
            assert examples
            found[str(target)]=dict(birth_ordinal=ordinal,visited_unique_nodes=len(child),seeds=examples)
    return found


def triplet_witness(old,lossless,native,out):
    ds={tuple(map(int,r[1:5])) for r in lines(lossless/"delta/declarations.txt") if r[0]=="D" and r[-1]=="M"}
    hits=rows(native/"hits.tsv")
    for row in rows(native/"imports.tsv"):
        if row["family"]!="M" or not any(int(row[k]) for k in ("watch_unit","watch_conflict","analyze","minimize")):continue
        doc=sample(old/"proof.bin",row,old,lossless,ds)
        triplets=[i for i,node in doc["P0_support"].items() if node.get("rule",[0])[0]==18]
        if not triplets:continue
        doc["triplet_nodes"]=triplets;doc["native_uses"]=[h for h in hits if h["id"]==row["id"]]
        save(out/"triplet-witness.json",doc)
        return dict(birth=int(row["id"]),nodes=len(doc["P0_support"]),triplet_nodes=triplets)
    raise AssertionError("no used mixed native proof with triplet ancestry")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("matrix","tools","checker","slice_checker","out"):p.add_argument(name,type=Path)
    p.add_argument("--case",action="append",help="limit independent replay to named frozen cases")
    a=p.parse_args();matrix,tools,checker,slicecheck,out=[v.resolve() for v in (a.matrix,a.tools,a.checker,a.slice_checker,a.out)]
    out.mkdir(parents=True,exist_ok=True)
    overall=json.loads((out/"audit.json").read_text()) if (out/"audit.json").exists() else {}
    for case in (a.case or json.loads((matrix/"plan.json").read_text())["preregistered"]["cases"]):
        base=matrix/case;dest=out/case;dest.mkdir()
        old=base/"AB/P0/native";peer=base/"AB/P1/native/boundary.tsv"
        compact=base/"compact/P0/native/proof.bin";source=BASE/"reports/evidence/d3/pairs"/case
        audited=dict(replay={},mapping={},boundary={});overall[case]=audited
        for fn in ("native-learns.tsv","native-theory.tsv"):unpack(source/(fn+".gz"),dest/fn)
        with (dest/"slice.tsv").open("w") as f:subprocess.run([slicecheck,old/"proof.bin",compact],stdout=f,check=True)
        audited["slice"]=numbers(dest/"slice.tsv")
        required=witnesses(compact);assert len(required)==audited["slice"]["matched_input_ordinals"]
        for label in ("legacy","A","eager","AB"):
            prod=base/label/"P0/native"
            assert native_digest(old/"model.tsv")==native_digest(prod/"model.tsv")
            audited["boundary"][label]=verify(prod/"proof.bin",dest/"native-theory.tsv")
        for mode in ("cross-d4","cross-d41","self-d4","self-d41"):
            self_pair=mode.startswith("self");new_map=mode.endswith("d41")
            run=dest/mode;run.mkdir()
            delta=run if self_pair else base/("AB" if new_map else "AB-old")/"P1/native"
            if self_pair:self_delta(old/"model.tsv",tools/"boolean-diff",run,new_map)
            delta_inputs(old,delta,run)
            labels=("legacy","AB","eager") if mode=="cross-d41" else ("legacy","AB") if not self_pair else ("AB",)
            for label in labels:
                check=run/label;check.mkdir()
                subprocess.run([checker,base/label/"P0/native/proof.bin",run/"inputs",run/"map",dest/"native-learns.tsv",
                                delta/"delta/declarations.txt",check],check=True)
                m=numbers(check/"metrics.tsv");audited["replay"][mode+"/"+label]=m
                if not self_pair and label=="AB":
                    runtime=rows(delta/"catalog.tsv")
                    checked=[list(map(int,r)) for r in lines(check/"learned.tsv")]
                    assert len(checked)==len(runtime)==m["births"]
                    for r,v in zip(runtime,checked):
                        assert [int(r[k]) for k in ("id","flags","has_B","alive","mapped")]==[v[0],v[2],v[11],v[7],v[8]]
                    selected=list(lines(delta/"eligible.tsv"))[1:]
                    assert [[r[0],*r[3:]] for r in selected]==list(lines(check/"survivors.tsv"))
                if label=="eager":
                    other=list(lines(run/"AB/learned.tsv"))
                    assert [r[1:] for r in lines(check/"learned.tsv")]==[r[1:] for r in other]
                    a1=list(lines(check/"survivors.tsv"));a2=list(lines(run/"AB/survivors.tsv"))
                    assert [r[1:] for r in a1]==[r[1:] for r in a2]
            used={int(r[0]) for r in lines(run/"AB/used.tsv")}
            audited["mapping"][mode]=map_audit(old/"model.tsv",old/"model.tsv" if self_pair else peer,delta/"delta",
                                               dest/"native-learns.tsv",used,required,run)
            assert audited["mapping"][mode]["final_mapped"]==audited["replay"][mode+"/AB"]["all_mappable"]
            if mode=="cross-d41" and case=="airline_reservations_6":
                audited["mapped_retirements"]=retired_examples(old/"proof.bin",delta,run)
        if case=="fib_updates_8":
            audited["witness"]=triplet_witness(old,base/"AB/P1/native",base/"all/P1/native",dest)
        save(out/"audit.json",overall)
        print("independent checks passed",case,flush=True)


if __name__=="__main__":main()
