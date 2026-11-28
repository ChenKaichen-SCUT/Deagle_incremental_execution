"""Production Compact worker, invoked while the first fully built P1 root is suspended."""
import csv
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from compact43 import DenseLibrary, OVERFLOW, require
from d1_identity import Keys, Model, load_rows
from d41_identity import pair_sites
from d42_events import unchanged, supplement
from diff_d1 import digest, one_var_table, compare_theory
from prepare_d3 import facts


FORMAT = "D43D-compact-production-v1"
RULES = "Closure-SC-d8c79eab/D41-triplets/D43B-dense-v2"
TOOLS = ("boolean-diff","compact-structure","compact43.py","d43_prepare.py","d1_identity.py","d1_theory.py",
         "d41_identity.py","d42_events.py","diff_d1.py","prepare_d3.py")
FILES = {"dense.bin","model.tsv"}
clock = time.monotonic_ns


def save(path,obj):
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n")


def tool_hashes(directory):
    return {name:digest(directory/name) for name in TOOLS}


def native_args(args, producer):
    valued={"--d4-search-log"}
    switches={"--d41-identities"}
    if producer:
        valued.update(("--d1-manifest","--d43-record"))
        switches.add("--d3-layouts")
    else:
        valued.update(("--d43-load","--d4-mode","--d4-out","--d4-tools"))
    kept=[];seen=set();it=iter(args)
    for word in it:
        if word in valued|switches:
            require(word not in seen,"repeated recorder/loader option")
            seen.add(word)
            if word in valued:
                require(bool(next(it,None)),"missing native option value")
        else:
            kept.append(word)
    require((valued|switches)-{"--d4-search-log"} <= seen,"missing producer/consumer option")
    require(kept.count("--mm")==1 and kept[kept.index("--mm")+1]=="sc" and "--deagle-closure" in kept and
            sum(kept.count(x) for x in ("--32","--64"))==1,"incompatible ABI or memory model")
    require(not any(k.startswith(("--d1-","--d2-","--d3-","--d4-","--d41-","--d42-","--d43-"))
                    for k in kept),"incompatible optional recorder or interface")
    return kept


def validate(lib,cfg,binary,args,tools):
    seal=lib/"library.json"
    expected=cfg["library_sha256"]
    require(digest(seal)==expected==(lib/"library.sha256").read_text().strip(),"P0 seal checksum")
    r=json.loads(seal.read_bytes())
    require(r["format"]==FORMAT and r["rules"]==RULES and r["mode"]=="compact" and
            r["capacities"]==[1024,1024] and r["overflow"]==1023 and r["status"] in (0,10) and
            r["elf"]==digest(binary) and r["tools"]==tool_hashes(tools) and r["case"]==cfg["case"] and
            r["inputs"] and set(r["files"])==FILES,"incompatible producer, rules, directory or tools")
    require(native_args(r["argv"],True)==native_args(args,False),"incompatible native configuration")
    for name in ("model.tsv","dense.bin"):
        meta=r["files"][name];p=lib/name
        require(p.is_file() and p.stat().st_size==meta["bytes"],"P0 payload length")
        if name=="dense.bin":
            data=p.read_bytes();actual=hashlib.sha256(data).hexdigest()
        else:
            actual=digest(p)
        require(actual==meta["sha256"],"P0 payload checksum")
    dense=DenseLibrary(data)
    require(dense.status==r["status"],"producer exit differs from compact footer")
    return r,dense


def models_and_ports(lib,out,tools,cfg,receipt):
    old,new=lib/"model.tsv",out/"boundary.tsv";delta=out/"delta";delta.mkdir()
    keys=Keys();rows=[load_rows(old,capture_graph=True),load_rows(new)]
    pairs=pair_sites(*rows,keys);events=[]
    patch=cfg.get("source_patch")
    if patch:
        name=patch["file"];original=lib.parent/"work"/name;current=Path.cwd()/name;diff=Path(patch["patch"])
        require(digest(original)==receipt["inputs"][name] and digest(current)==patch["new_sha256"] and
                digest(diff)==patch["patch_sha256"],"unbound source correspondence")
        events=supplement(rows,pairs,keys,name,unchanged(original.read_bytes(),current.read_bytes(),diff.read_bytes()))
    models=[Model(p,keys,True,live_boundary=bool(i),recorded_queries=not i,records=rows[i],site_pairs=pairs[i])
            for i,p in enumerate((old,new))]
    a,b=models
    require(a.rows["END"]==[(str(receipt["status"]),)] and a.rows["K"]==b.rows["K"],"incompatible model semantics")
    anchors=[delta/"P0.anchors",delta/"P1.anchors"]
    for i in (0,1):
        models[i].write_anchors(models[1-i],anchors[i])
    subprocess.run([tools/"boolean-diff",old,new,*anchors,delta,"--d41-map-only"],check=True)
    ports,counts=one_var_table(delta/"variables.tsv",models)
    return models,ports,counts,events


def certify(models,ports,old,out):
    rows=[];delta=out/"delta";summary=compare_theory(models,ports,delta,old_rows=rows)
    cert=delta/"declarations.txt"
    facts(old,delta,cert,graph_lines=models[0].rows["_GRAPH"],declaration_rows=rows)
    known={}
    with cert.open() as stream:
        for line in stream:
            if line.startswith("D "):
                _,op,a,b,c,state=line.split();key=tuple(map(int,(op,a,b,c)))
                require(key not in known and state in ("M","C","U"),"invalid theory certificate")
                known[key]=state
    return known,summary


def effective(path,n0,n1):
    sides=[[-1],[-1]]
    with path.open() as f:
        for row in csv.DictReader(f,delimiter="\t"):
            side=int(row["side"]);v=int(row["variable"])
            require(side in (0,1) and v==len(sides[side]),"incomplete signed correspondence")
            sides[side].append(int(row["peer"]))
    require([len(s) for s in sides]==[n0,n1],"map dimensions")
    for a,b in (sides,sides[::-1]):
        for v,peer in enumerate(a):
            require(peer==-1 or (2<=peer<2*len(b) and b[peer//2]==2*v+(peer&1)),"invalid signed injection")
    return sides[0]


def dirty(dense,flags,cert,mu,out):
    masks=[0,0];counts=[Counter(),Counter()]
    with (out/"input-matches.tsv").open() as file:
        matches=csv.DictReader(file,delimiter="\t")
        for i,flag in enumerate(flags):
            if not flag&3:
                continue
            row=next(matches,None)
            require(row and int(row["occurrence"])==i+1,"missing or misordered Boolean membership")
            hit=int(row["P1_permanent_occurrence"]);slot=dense.slots[0][dense.boolean[i]]
            counts[0]["matched" if hit>0 else "unmapped" if hit<0 else "mapped_absent"]+=1
            if hit<=0:
                masks[0] |= 1<<slot
        require(next(matches,None) is None,"extra Boolean membership")
    with (out/"theory-matches.tsv").open("x") as f:
        print("op\ta\tb\tc\tgroup\tslot\tobserved\tstate",file=f)
        for fact,(i,group) in dense.theory.items():
            slot=dense.slots[1][group];used=dense.observed(1,i)
            require(fact in cert,"declaration absent from the producer model")
            if not used and slot!=OVERFLOW:
                continue
            state=cert[fact]
            if state=="M" and fact[0] in (3,4) and fact[3]>=2:
                require(fact[3]//2<len(mu) and mu[fact[3]//2]>=2,"uncertified RF/Guard binding")
            counts[1][{"M":"matched","C":"changed","U":"unknown"}[state]]+=1
            if state!="M":
                masks[1] |= 1<<slot
            print(*fact,group,slot,int(used),state,sep="\t",file=f)
    return masks,counts


def choose(dense,mu,masks,nvars,out):
    by_class={k:Counter() for k in ("B","M","T","scope_only")}
    chosen=[];eligible=0
    with (out/"births.tsv").open("x") as report,(out/"eligible.tsv").open("x") as pool:
        print("ordinal\tclass\tscope\tmapped\tdirty_B\tdirty_T\teligible\tchosen",file=report)
        for i,flags,lits,b,t in dense.births():
            family=("scope_only","B","T","M")[flags&3] if flags&3 or flags&12 else "B"
            bucket=by_class[family];bucket["births"]+=1
            scope="unknown" if flags&8 else "query" if flags&4 else "permanent"
            if lits is None:
                bucket[scope]+=1
                print(i,family,scope,"-","-","-",0,0,sep="\t",file=report);continue
            bucket["permanent"]+=1
            mapped=all(mu[l//2]>=2 for l in lits);bucket["mapped"]+=mapped
            db,dt=bool(b&masks[0]),bool(t&masks[1]);accept=mapped and not (db or dt)
            take=accept and len(chosen)<512
            if accept:
                eligible+=1;bucket["eligible"]+=1
                row="\t".join(map(str,(i,family,len(lits),*(mu[l//2]^(l&1) for l in lits))))+"\n"
                pool.write(row)
                if take:
                    chosen.append(row);bucket["chosen"]+=1
            print(i,family,scope,int(mapped),int(db),int(dt),int(accept),int(take),sep="\t",file=report)
    with (out/"selected.tmp").open("x") as f:
        print("D4-selected-v1",nvars,len(chosen),sep="\t",file=f)
        f.writelines(chosen)
    return dict(policy="first512",births=len(dense.records),eligible=eligible,chosen=len(chosen),classes=by_class)


def prepare(lib,out,tools):
    start=clock();stage=start;times={}
    def mark(name):
        nonlocal stage
        now=clock();times[name]=now-stage;stage=now
    require(not (out/"ready.tsv").exists(),"stale native batch")
    cfg=json.loads((out/"control43.json").read_bytes())
    parent=Path("/proc")/str(os.getppid())
    args=(parent/"cmdline").read_bytes().rstrip(b"\0").decode().split("\0")[1:]
    rec,dense=validate(lib,cfg,parent/"exe",args,tools)
    flags=dense.occurrence_flags()
    mark("archive_read_validate")
    models,ports,variables,events=models_and_ports(lib,out,tools,cfg,rec)
    n0,n1=(m.nvars for m in models);mark("semantic_variables_and_static_models")
    dense.validate_payload(n0,flags);mark("archive_payload_semantics")
    cert,theory=certify(models,ports,lib/"model.tsv",out);mark("theory_bindings")
    input_path=out/"compact-occurrences.bin";input_path.write_bytes(flags)
    subprocess.run([tools/"compact-structure",lib/"model.tsv",out/"boundary.tsv",out/"delta/variables.tsv",
                    input_path,out,str(n0),str(n1)],check=True)
    mu=effective(out/"effective-map.tsv",n0,n1);mark("structural_and_membership")
    masks,checked=dirty(dense,flags,cert,mu,out);mark("dirty")
    policy=choose(dense,mu,masks,n1,out);mark("label_filter")
    save(out/"policy.json",policy)
    save(out/"compact-delta.json",dict(producer=cfg["library_sha256"],variables=variables,extra_sites=events,
         theory=theory,checked=checked,dirty_slots=[[i for i in range(1024) if m>>i&1] for m in masks],
         groups=list(map(len,dense.keys)),time_ns=times,
         inputs_read=["library.json","library.sha256","dense.bin","model.tsv"],
         publication_before_rename_ns=clock()-start))
    (out/"selected.tmp").rename(out/"ready.tsv")


if __name__=="__main__":
    prepare(*(Path(arg) for arg in sys.argv[1:]))
