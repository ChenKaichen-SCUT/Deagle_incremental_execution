"""Classify every retired birth by its actual reachable failed leaves and untranslatable interface roles."""
import argparse,csv,json,mmap,struct
from collections import Counter,defaultdict
from pathlib import Path
from cases42 import load
from d42_prepare import read,save

def rows(file):
    with file.open() as f:yield from csv.DictReader(f,delimiter="\t")

def report(old,new,out):
    causes=("unmapped_boolean_leaf","translated_premise_absent","changed_theory","unknown_theory_binding","query_scope",
            "incomplete_or_opaque","unmapped_conclusion")
    b={int(r["occurrence"]):r["status"] for r in rows(new/"inputs42.tsv")}
    theory={tuple(map(int,line.split()[1:5])):line.split()[-1] for line in (new/"delta/declarations.txt").open() if line.startswith("D ")}
    role={int(v):r for side,v,_,r,why,anchor in (line.split() for line in (new/"delta/variables.tsv").open()) if side=="0"}
    missing={int(r["variable"]) for r in rows(new/"effective-map.tsv") if r["side"]=="0" and int(r["peer"])<0}
    cat=iter(rows(new/"catalog42.tsv"));joint=Counter();individual=Counter();roles=Counter();first={}
    with (old/"proof.bin").open("rb") as file,mmap.mmap(file.fileno(),0,access=mmap.ACCESS_READ) as data:
        at=12;sections=[]
        for size in (16,4,8,16,12,8,12,4,4,4,4,4,20):
            n=struct.unpack_from("<I",data,at)[0];sections.append((at+4,n));at+=4+size*n
        nodes,lits,edges=sections[:3];mask=bytearray(nodes[1]);mask[0]=32;occ=rec=birth=0;prev_end=prev_lit=0
        for i,(hi,end,k,flag) in enumerate(struct.iter_unpack("<4I",data[nodes[0]:nodes[0]+16*nodes[1]])):
            x=0
            if k in (1,2,3):
                occ+=1
                if k==1:x={"unmapped":1,"mapped_absent":2,"matched":0}.get(b.get(occ),0)
                else:x=16 if k==2 else 32
            elif k==0 or k in (7,8,9,11):x=32
            elif k in (12,13):
                rid,op,a,bt,c=struct.unpack_from("<IIiii",data,sections[12][0]+20*rec);rec+=1;assert rid==i
                if k==12:x={"M":0,"C":4,"U":8}[theory[(op,a,bt,c)]]
            for j in range(prev_end,end):x|=mask[struct.unpack_from("<I",data,edges[0]+8*j)[0]]
            mask[i]=x
            if k==6:
                birth+=1;entry=next(cat);assert int(entry["ordinal"])==birth
                raw=struct.unpack_from("<"+str(hi-prev_lit)+"i",data,lits[0]+4*prev_lit)
                unmapped={role.get(l//2,"unknown") for l in raw if l//2 in missing or l<2}
                assert bool(unmapped)==(entry["conclusion_mapped"]=="0") and (x==0)==(entry["support_alive"]=="1")
                if unmapped:x|=64
                assert (x==0)==(entry["eligible"]=="1")
                label="+".join(n for bit,n in enumerate(causes) if x&(1<<bit)) or "eligible"
                joint[label]+=1;first.setdefault(label,birth)
                for bit,n in enumerate(causes):
                    if x&(1<<bit):individual[n]+=1
                roles.update(unmapped)
            prev_end=end;prev_lit=hi
    assert next(cat,None) is None
    return dict(births=birth,exclusive=joint,overlapping=individual,unmapped_conclusion_roles=roles,first_birth=first)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("functional",type=Path);p.add_argument("out",type=Path);a=p.parse_args()
    result={}
    for case in load():
        d=a.functional/case/"1";result[case]=report(d/"reference/P0/native",d/"Combined/P1/native",a.out)
    save(a.out,result)
