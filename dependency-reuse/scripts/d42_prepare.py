"""Validate the P0 producer and prepare the live native P1 boundary. No proof replay here."""
import csv
import json
import os
from pathlib import Path
import subprocess
import time

from d1_identity import Keys,Model,load_rows
from d41_identity import pair_sites
from d42_events import unchanged,supplement,inventory
from diff_d1 import digest,one_var_table,compare_theory
from prepare_d3 import facts

TOOLS=("boolean-diff","select42","d4_prepare.py","d42_prepare.py","d42_events.py",
       "d1_identity.py","d1_theory.py","d41_identity.py","diff_d1.py","prepare_d3.py")

def tool_hashes(tools):return {n:digest(tools/n) for n in TOOLS}

def read(path):return json.loads(path.read_text())

def save(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")

def validate(lib,binary,tools):
    path=lib/"receipt42.json"
    if digest(path)!=(lib/"receipt42.sha256").read_text().strip():raise ValueError("P0 receipt checksum")
    r=read(path)
    if (r["format"]!="D42-SC-v1" or r["mode"] not in ("light","audit") or r["status"] not in (0,10) or
        r["elf"]!=digest(binary) or r["tools"]!=tool_hashes(tools) or not r["inputs"] or
        set(r["files"])!={"proof.bin","model.tsv","proof.bin.quality.tsv"}):raise ValueError("incompatible native P0 library")
    if any(digest(lib/name)!=value for name,value in r["files"].items()):raise ValueError("P0 library mismatch")
    with (lib/"proof.bin").open("rb") as f:
        head=f.read(8);f.seek(-8,2);end=f.read()
    if head!=(b"DEAGSL1\0" if r["mode"]=="light" else b"DEAGD3\x02\x00") or end!=r["status"].to_bytes(4,"little")+(b"ENDL" if r["mode"]=="light" else b"END3"):
        raise ValueError("native proof origin or completion mismatch")
    return r

def select(out,quality,nvars,policy):
    if policy not in ("all","top512"):raise ValueError("unsupported policy")
    by_id={}
    with (out/"batch-rows.tsv").open() as f:
        for row in f:
            k,kind,n,*lits=row.split()
            if kind not in ("B","T","M") or int(n)!=len(lits) or int(k) in by_id:raise ValueError("invalid eligible birth")
            by_id[int(k)]=(int(n),row)
    options=[];total=0
    with quality.open() as f:
        for q in csv.DictReader(f,delimiter="\t"):
            total+=1;i=int(q["ordinal"])
            if i!=total:raise ValueError("discontinuous P0 birth history")
            if i not in by_id:continue
            length,row=by_id[i];lbd=int(q["lbd"])
            if length!=int(q["length"]) or not 1<=lbd<=length:raise ValueError("different P0 birth")
            visits=sum(int(q[k]) for k in ("propagations","conflicts","analyze"))
            options.append((lbd,length,-visits,i))
    if len(options)!=len(by_id):raise ValueError("missing P0 birth history")
    ranked=sorted(options);chosen=ranked if policy=="all" else ranked[:512]
    with (out/"selected.tmp").open("x") as f:
        print("D4-selected-v1",nvars,len(chosen),sep="\t",file=f)
        for _,_,_,i in sorted(chosen,key=lambda x:x[-1]):f.write(by_id[i][1])
    with (out/"ranking.tsv").open("w") as f:
        print("rank\tordinal\tlbd\tlength\tp0_visits\tchosen",file=f)
        for j,(l,n,u,i) in enumerate(ranked,1):print(j,i,l,n,-u,int(j<=len(chosen)),sep="\t",file=f)
    return dict(policy=policy,births=total,eligible=len(by_id),chosen=len(chosen))

def prepare(lib,out,tools):
    start=time.monotonic_ns();cfg=read(out/"control42.json")
    r=validate(lib,Path(f"/proc/{os.getppid()}/exe"),tools)
    if cfg["case"]!=r["case"] or cfg["mapping"] not in ("semantic","structure"):raise ValueError("wrong cohort or mapping")
    after_check=time.monotonic_ns()
    old,new=lib/"model.tsv",out/"boundary.tsv";delta=out/"delta";delta.mkdir()
    keys=Keys();records=[load_rows(old,capture_graph=True),load_rows(new)];pairs=pair_sites(*records,keys)
    event_witness=[]
    if cfg.get("source_patch") and cfg["mapping"]=="structure":
        p=cfg["source_patch"];f=p["file"];z=lib.parent/"work"/f;w=Path.cwd()/f
        if digest(z)!=r["inputs"][f] or digest(w)!=p["new_sha256"] or digest(Path(p["patch"]))!=p["patch_sha256"]:raise ValueError("unbound source correspondence")
        lines=unchanged(z.read_bytes(),w.read_bytes(),Path(p["patch"]).read_bytes())
        event_witness=supplement(records,pairs,keys,f,lines)
    models=[Model(path,keys,True,live_boundary=bool(i),recorded_queries=not i,records=records[i],site_pairs=pairs[i])
            for i,path in enumerate((old,new))]
    a,b=models
    if a.rows["END"]!=[(str(r["status"]),)] or a.rows["K"]!=b.rows["K"]:raise ValueError("incompatible permanent model configuration")
    after_models=time.monotonic_ns()
    anchors=[delta/"P0.anchors",delta/"P1.anchors"]
    for i in (0,1):models[i].write_anchors(models[1-i],anchors[i])
    subprocess.run([tools/"boolean-diff",old,new,*anchors,delta,"--d41-map-only"],check=True)
    maps,variables=one_var_table(delta/"variables.tsv",models);after_vars=time.monotonic_ns()
    old_rows=[];theory=compare_theory(models,maps,delta,old_rows=old_rows)
    facts(old,delta,delta/"declarations.txt",graph_lines=records[0]["_GRAPH"],declaration_rows=old_rows)
    before_select=time.monotonic_ns()
    subprocess.run([tools/"select42",lib/"proof.bin",old,new,delta/"variables.tsv",delta/"declarations.txt",out,
                    str(a.nvars),str(b.nvars),cfg["mapping"]],check=True)
    after_select=time.monotonic_ns()
    policy=select(out,lib/"proof.bin.quality.tsv",b.nvars,cfg["policy"])
    save(out/"policy.json",policy)
    save(out/"delta42.json",dict(library=digest(lib/"receipt42.json"),boundary=digest(new),config=cfg,variables=variables,
        events=inventory(models),extra_sites=event_witness,theory=theory,timings_ns=dict(
            receipt=after_check-start,models=after_models-after_check,anchors=after_vars-after_models,
            theory=before_select-after_vars,transport=after_select-before_select,ranking_and_seal=time.monotonic_ns()-after_select)))
    (out/"selected.tmp").rename(out/"ready.tsv")
