"""Offline D4 replay, native-use audit and accounting on all 44,029 births in both recording arms."""
import argparse
import csv
import gzip
import json
import struct
import subprocess
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from diff_d1 import digest
from run_stock import BASE, save
from verify_d3_boundary import verify


def rows(p):
    with p.open() as f:return list(csv.DictReader(f,delimiter="\t"))


def numbers(path):
    return {k:int(v) for k,v in (l.split() for l in path.read_text().splitlines())}


def bits(s):
    return list(map(int,s.split()))


def unpack(file,dest):
    import shutil
    with gzip.open(file,"rb") as src,dest.open("wb") as dst:shutil.copyfileobj(src,dst)


def delta_inputs(old,new,tmp):
    delta=new/"delta"
    counts={int(k) for k,scope,n0,n1 in (l.split() for l in (delta/"clause-counts.tsv").read_text().splitlines()) if int(n1)}
    with (delta/"variables.tsv").open() as f,(tmp/"map").open("w") as out:
        for l in f:
            side,var,to,*_=l.split()
            if side=="0" and int(to)>=0:out.write(f"{var} {to}\n")
    with (delta/"occurrences.tsv").open() as f,(old/"model.tsv").open() as m,(tmp/"inputs").open("w") as out:
        for i,text in enumerate((r for r in m if r.startswith("C\t")),1):
            _,scope,*lits=text.split()
            side,seq,s,key,why=f.readline().split()
            assert side=="0" and i==int(seq) and scope==s
            print(scope,int(int(key) not in counts),*lits,file=out)
        assert not (f.readline().startswith("0\t"))


def sample(proof,row,old,new,decls):
    data=proof.read_bytes();at=12;sections=[]
    for width in (16,4,8,16,12,8,12,4,4,4,4,4,20):
        n=struct.unpack_from("<I",data,at)[0];at+=4;sections.append((at,n));at+=width*n
    n,l,e,inp=map(lambda x:x[0],sections[:4]);target=int(row["id"])
    within={};pending=[target]
    while pending:
        i=pending.pop()
        if i in within:continue
        lo,eb=struct.unpack_from("<II",data,n+16*(i-1))
        hi,ee,kind,flags=struct.unpack_from("<IIII",data,n+16*i)
        parents=[struct.unpack_from("<Ii",data,e+8*j) for j in range(eb,ee)]
        within[i]=dict(kind=kind,flags=flags,parents=parents,raw_clause=struct.unpack_from("<"+"i"*(hi-lo),data,l+4*lo))
        assert not flags & 7
        pending.extend(p for p,_ in parents)
    leaves={struct.unpack_from("<I",data,inp+j*16)[0]:j+1 for j in range(sections[3][1])}
    terms={leaves[i]:i for i,r in within.items() if r["kind"]==1}
    matched={}
    with (new/"delta/occurrences.tsv").open() as f:
        for line in f:
            side,seq,scope,leaf,_=line.split()
            if side=="0" and int(seq) in terms:
                assert scope=="B" and int(leaf)>0
                matched.setdefault(leaf,[]).append(terms[int(seq)])
                within[terms[int(seq)]]["P0_input"]=int(seq)
            if side=="1" and leaf in matched:
                for node in matched.pop(leaf):
                    within[node].update(matched_key=int(leaf),P1_input=int(seq))
    assert not matched
    rule_at,count=sections[12]
    for j in range(count):
        node,op,a,b,c=struct.unpack_from("<IIiii",data,rule_at+20*j)
        if node not in within:continue
        within[node]["rule"]=[op,a,b,c]
        if within[node]["kind"]==12:
            assert (op,a,b,c) in decls
            within[node]["P1_declaration_status"]="M"
    return dict(id=target,family=row["family"],P0_proof_sha256=digest(proof),
                P1_boundary_sha256=digest(new/"boundary.tsv"),P1_signed_translation=bits(row["translated"]),
                native_disposition=row["disposition"],P0_support=within)


def audit(checker,arm,mode,pair,out):
    old,new=arm/"P0/native",arm/"P1/native"
    catalog=rows(new/"catalog.tsv")
    with gzip.open(pair/"improved-learned.tsv.gz","rt") as f:d3=[bits(l) for l in f]
    assert len(d3)==len(catalog)
    classes=Counter()
    for prev,now in zip(d3,catalog):
        ident,size,flags,direct,cause,res,unit,alive,mapped,u,m,has_b,mixed=prev
        assert [int(now[k]) for k in ("id","flags","has_B","alive","mapped","selected")]==[ident,flags,has_b,alive,mapped,alive*mapped]
        cat=("unknown_theory" if flags&1 else "incomplete" if flags&4 else "query" if flags&2 else
             "boolean" if not flags else "mixed" if mixed else "theory_only")
        classes[cat]+=1
    batch=(new/"ready.tsv").read_text().splitlines()
    header=batch[0].split()
    selected=[l.split() for l in batch[1:]]
    with gzip.open(pair/"improved-survivors.tsv.gz","rt") as f:ref=[bits(l) for l in f]
    assert int(header[2])==len(selected)==len(ref) and [[int(r[0]),*map(int,r[3:])] for r in selected]==ref
    with TemporaryDirectory() as wd:
        tmp=Path(wd)
        for name in ("native-learns.tsv","native-theory.tsv"):unpack(pair/(name+".gz"),tmp/name)
        boundary=verify(old/"proof.bin",tmp/"native-theory.tsv")
        delta_inputs(old,new,tmp)
        subprocess.run([checker,old/"proof.bin",tmp/"inputs",tmp/"map",tmp/"native-learns.tsv",
                        new/"delta/declarations.txt",out],check=True)
    assert [bits(l) for l in (out/"survivors.tsv").read_text().splitlines()]==ref
    families={k:Counter() for k in ("B","M","T")}
    imports=rows(new/"imports.tsv")
    hits=rows(new/"hits.tsv");names=("watch_unit","watch_conflict","analyze","minimize")
    by_id={int(r["id"]):r for r in imports};first=set()
    assert len(imports)==len(ref)
    for r,pre in zip(imports,selected):
        assert int(r["id"])==int(pre[0]) and r["family"]==pre[1] and bits(r["translated"])==list(map(int,pre[3:]))
        c=families[r["family"]];c["candidates"]+=1
        c[r["disposition"]]+=1
        for k in names:c[k]+=int(r[k])
        c["rows_used"]+=any(int(r[k]) for k in names)
        c["rows_moved"]+=int(r["moves"])>0
        c["rows_removed"]+=r["disposition"]=="attached" and int(r["current_cref"])==2**32-1
        c["root_false_removed"]+=len(bits(r["root_false"]))
        assert (r["disposition"]=="check_only")== (mode=="record-cold")
    for h in hits:
        i,k=int(h["id"]),int(h["use"]);r=by_id[i]
        assert (i,k) not in first and int(r[names[k]])>0 and r["disposition"]=="attached"
        assert sorted(bits(h["clause"]))==bits(r["installed"])
        if k in (0,1):assert int(h["raw_literal"])==bits(h["clause"])[0]
        first.add((i,k))
    assert first=={(i,k) for i,r in by_id.items() for k in range(4) if int(r[names[k]])}
    examples={}
    if mode=="reuse":
        dpath=new/"delta/declarations.txt"
        decls={tuple(map(int,x[1:5])) for x in (l.split() for l in dpath.read_text().splitlines()) if x[0]=="D" and x[-1]=="M"}
        for f in ("B","M","T"):
            r=next((r for r in imports if r["family"]==f and any(int(r[k]) for k in names)),None)
            if r is None:continue
            doc=sample(old/"proof.bin",r,old,new,decls)
            doc["first_native_uses"]=[h for h in hits if h["id"]==r["id"]]
            save(out/("witness-"+f+".json"),doc);examples[f]=int(r["id"])
    return dict(classes=classes,independent_births=len(d3),independent_native_boundaries=boundary,
                offline_checked=numbers(out/"metrics.tsv"),families=families,examples=examples,
                selection=numbers(new/"selection.tsv"),import_cost=numbers(new/"import-time.tsv"),
                preparation=json.loads((new/"delta.json").read_text())["timings_ns"],library_bytes=(old/"proof.bin").stat().st_size,
                first_event_receipts=len(hits))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ("runs","checker","new_directory"):p.add_argument(n,type=Path)
    a=p.parse_args();r,c,d=[v.resolve() for v in (a.runs,a.checker,a.new_directory)]
    d.mkdir(parents=True,exist_ok=False)
    data={}
    for case in json.loads((r/"summary.json").read_text()):
        data[case]={}
        pair=BASE/"reports/evidence/d3/pairs"/case
        for mode in ("record-cold","reuse"):
            out=d/case/mode;out.mkdir(parents=True)
            data[case][mode]=audit(c,r/case/mode,mode,pair,out)
        for k in ("catalog.tsv","ready.tsv"):
            assert digest(r/case/"reuse/P1/native"/k)==digest(r/case/"record-cold/P1/native"/k)
    save(d/"audit.json",data)
    print("all six recorded archives replayed; both arms agree on every candidate")


if __name__=="__main__":main()
