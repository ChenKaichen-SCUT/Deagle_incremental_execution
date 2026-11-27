"""Reallocate A's full P0 group keys densely; hold the D4.2 map and leaf verdicts fixed."""
import argparse
from collections import Counter
import csv
import gzip
import json
from pathlib import Path
import struct
import subprocess
from d43_project_support import BASE, PLAN, PAIR, FACT, canonical, check, digest, event_owner, theory_key, installed, registry, save
from d43_review import write_tsv, family

A = BASE/"reports/evidence/d43a"
CASES = PLAN["cases"]


def leaf_rows(data):
    nb,nt=struct.unpack_from("<II",data,8)
    for i in range(nb):
        yield 0,i+1,PAIR.unpack_from(data,16+8*i)
    p=16+8*nb
    for i in range(nt):
        yield 1,FACT.unpack_from(data,p),PAIR.unpack_from(data,p+16)
        p+=24
    check(p==len(data),"invalid leaf directory")


def inventory(old,new):
    scopes,events,names={},{},{}
    with (old/"model.tsv").open() as f:
        for line in f:
            tag=line.partition("\t")[0]
            if tag not in ("X","E","NODE"):continue
            v=line.rstrip("\n").split("\t")[1:]
            if tag=="X":scopes[int(v[0])]=(int(v[1]),int(v[2]))
            elif tag=="NODE":names[int(v[0])]=v[1]
            else:
                name,ctx,role,obj,_,storage=v
                owner=event_owner(ctx,role,obj,storage,scopes)
                events[name]=None if name in events and owner!=events[name] else owner
    registered,receipt=registry(old/"proof.bin")
    cert=installed(new/"delta/declarations.txt",receipt)
    for fact in sorted(cert.keys()-registered.keys()):
        yield fact,cert[fact],canonical(theory_key(fact,events,names)).decode()


def reference(path):
    with path.open("rb") as f:
        check(f.read(8)==b"D43REF1\0","reference header")
        n,=struct.unpack("<I",f.read(4))
        for i in range(1,n+1):
            flags,node,nl=struct.unpack("<III",f.read(12))
            lits=f.read(4*nl);check(len(lits)==4*nl,"reference clause")
            yield i,flags,node,lits,int.from_bytes(f.read(128),"little"),int.from_bytes(f.read(128),"little")
        check(not f.read(1),"reference end")


def case_run(case,d42,out,engine):
    src=A/"cases"/case
    with gzip.open(src/"groups.tsv.gz","rt") as f:
        groups=list(csv.DictReader(f,delimiter="\t"))
    ids=[{},{}];catalog={}
    for row in groups:
        key=row["canonical_key"];d=int(json.loads(key)[0]=="T")
        group=len(ids[d]);check(key not in ids[d],"duplicate group")
        ids[d][key]=group;catalog[int(row["id"])]=(d,group)
    data=bytearray(gzip.decompress((src/"leaves.bin.gz").read_bytes()))
    nb,nt=struct.unpack_from("<II",data,8)
    dirty={s:[set(),set()] for s in ("U_audit","U_all","expanded")}
    for index,(d,local,(gid,_,state,use)) in enumerate(leaf_rows(data)):
        if state>=5:continue
        side,group=catalog[gid];check(side==d,"domain")
        pos=16+8*index if not d else 16+8*nb+24*(index-nb)+16
        struct.pack_into("<H",data,pos+4,min(group,1023))
        if state:
            for mode,row in dirty.items():
                if mode!="U_audit" or use&2:row[d].add(group)
    old=d42/"functional"/case/"1/reference/P0/native"
    new=d42/"functional"/case/"1/Mapping-only/P1/native"
    before=list(map(len,ids))
    extension=0
    for fact,state,key in inventory(old,new):
        gid=ids[1].setdefault(key,len(ids[1]))
        if state:dirty["expanded"][1].add(gid)
        extension+=1
    # Separate full-key loss and overflow even for cohorts that spill. Actual
    # registered identities are retained independently of their physical bit.
    out.mkdir(parents=True,exist_ok=True)
    (out/"dense-leaves.bin").write_bytes(data)
    subprocess.run([engine,old/"proof.bin",out/"dense-leaves.bin",out/"expected.bin"],check=True)
    ref=list()  # only the small exact candidate pool needs further set queries
    with gzip.open(src/"births.tsv.gz","rt") as f:
        for raw,(i,flags,n,_,b,t) in zip(csv.DictReader(f,delimiter="\t"),reference(out/"expected.bin"),strict=True):
            check(i==int(raw["ordinal"]) and n==int(raw["audit_id"]),"birth alignment")
            if not flags&7 and raw["mapped"]=="1" and not int(raw["mask"])&15:
                ref.append((i,family(flags,int(raw["has_b"])),b,t))
    check(max(before)<=1023,"frozen registered case unexpectedly overflows; exact group oracle required")
    results={}
    for mode,row in dirty.items():
        # All candidate supports here are among registered groups with unique slots.
        logical=[sum(1<<g for g in rs if g<1023) for rs in row]
        physical=[sum(1<<s for s in {min(g,1023) for g in rs}) for rs in row]
        counts=Counter()
        for _,fam,b,t in ref:
            counts["exact_"+fam]+=1
            if not (b&logical[0] or t&logical[1]):counts["group_"+fam]+=1
            if not (b&physical[0] or t&physical[1]):counts["dense_"+fam]+=1
        results[mode]=dict(counts)
    result=dict(case=case,registered_groups=before,expanded_groups=list(map(len,ids)),
                overflow_registered=[max(0,n-1023) for n in before],
                overflow_expanded=[max(0,len(m)-1023) for m in ids],
                expanded_extra_declarations=extension,results=results)
    save(out/"offline.json",result)
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("d42","engine","out"):p.add_argument(k,type=Path)
    a=p.parse_args();results=[case_run(c,a.d42,a.out/c,a.engine) for c in CASES]
    for u,tot,mixed in (("U_audit",330,264),("U_all",311,264)):
        counts=sum((Counter(r["results"][u]) for r in results),Counter())
        check(sum(counts["dense_"+k] for k in "BMT")==tot and counts["dense_M"]==mixed,"approved reference totals")
    save(a.out/"dense-preflight.json",results)
