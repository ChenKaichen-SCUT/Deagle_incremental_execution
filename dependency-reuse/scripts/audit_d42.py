"""Offline independent membership, support, actual derivation, history and import audits for every birth."""
import argparse,csv,json,subprocess,sys
from collections import Counter
from pathlib import Path
from audit_d4 import numbers
from cases42 import load
from d42_prepare import read,save,tool_hashes
from diff_d1 import digest
from run_stock import BASE
from verify_d3_boundary import verify


def table(path):
    with path.open() as f:yield from csv.DictReader(f,delimiter="\t")

def keyed(path):return {k:(v if k=="stop" else int(v)) for k,v in (l.split() for l in path.read_text().splitlines())}

def native_n(path):
    with path.open() as f:return max(int(l.split()[1]) for l in f if l.startswith("N\t"))

def premises(old,new,arm,out):
    maps=[{},{}]
    for row in table(arm/"effective-map.tsv"):
        s,v,p=map(int,(row["side"],row["variable"],row["peer"]))
        if p>=0:maps[s][v]=p
    assert len(maps[0])==len(maps[1]) and all(maps[1][p//2]==2*v+(p&1) for v,p in maps[0].items())
    def canon(c):return tuple(sorted(set(c)))
    pool={};n=0
    with new.open() as f:
        for row in f:
            if row.startswith("C\t"):
                n+=1
                if row.split()[1]=="B":pool.setdefault(canon(map(int,row.split()[2:])),n)
    with (out/"map").open("w") as f:
        for var,peer in maps[0].items():print(var,peer,file=f)
    claims={int(r["occurrence"]):r for r in table(arm/"inputs42.tsv")}
    structural={int(r["old_var"]):r for r in table(arm/"structure.tsv")};by_new={}
    for v,r in structural.items():
        assert maps[0][v]==int(r["new_signed_positive"])
        by_new.setdefault(int(r["new_occurrence"]),[]).append(r)
    witness={}
    with new.open() as f:
        seq=0
        for row in f:
            if row.startswith("C\t"):
                seq+=1
                if seq in by_new:
                    _,scope,*lits=row.split();assert scope=="B"
                    witness[seq]=canon(map(int,lits))
    by_old={}
    for v,r in structural.items():by_old.setdefault(int(r["old_occurrence"]),[]).append(r)
    cnt=Counter();ids=set();ordinal=0
    with old.open() as f,(out/"inputs").open("w") as dst:
        for row in f:
            if not row.startswith("C\t"):continue
            ordinal+=1;_,scope,*raw=row.split();lits=list(map(int,raw))
            good=all(l in (-1,-2) or l//2 in maps[0] for l in lits)
            trans=canon(l if l<0 else maps[0][l//2]^(l&1) for l in lits) if good else None
            occ=pool.get(trans,0) if scope=="B" else 0
            print(scope,int(not occ),*lits,file=dst)
            for r in by_old.get(ordinal,[]):
                assert scope=="B" and trans==witness[int(r["new_occurrence"])] and int(r["old_var"]) in {l//2 for l in lits}
            if ordinal in claims:
                r=claims[ordinal];status="scope" if scope!="B" else "matched" if occ else "mapped_absent" if good else "unmapped"
                assert r["status"]==status and int(r["p1_permanent_occurrence"])==occ
                cnt[status]+=1;ids.add(ordinal)
    assert ids==set(claims)
    return dict(injective_pairs=len(maps[0]),premises=cnt,structural_signed_occurrences=len(structural))

def catalog(p):return [(int(r["flags"]),int(r["has_b"]),int(r["support_alive"]),int(r["conclusion_mapped"]),int(r["eligible"])) for r in table(p/"catalog42.tsv")]

def check_history(path):
    return [tuple(int(r[k]) for k in ("ordinal","length","lbd","propagations","conflicts","analyze","resident"))
            for r in table(path/"proof.bin.quality.tsv")]

def imports(arm):
    ready=(arm/"ready.tsv").read_text().splitlines();batch=[r.split() for r in ready[1:]]
    logs=list(table(arm/"imports.tsv"));assert len(logs)==int(ready[0].split()[2])==len(batch)
    hits=list(table(arm/"hits.tsv"));names=["watch_unit","watch_conflict","analyze","minimize"];keys=set()
    for r,b in zip(logs,batch):assert r["id"]==b[0] and r["family"]==b[1] and r["translated"].split()==b[3:]
    for h in hits:
        k=int(h["use"]);target=(int(h["id"]),k);assert target not in keys;keys.add(target)
        r=next(r for r in logs if r["id"]==h["id"]);assert int(r[names[k]])>0 and sorted(h["clause"].split())==sorted(r["installed"].split())
    assert keys=={(int(r["id"]),k) for r in logs for k,n in enumerate(names) if int(r[n])}
    return {int(r["id"]) for r in logs if any(int(r[n]) for n in names)}

def controlled(case,controls,tools,lib,out,expected):
    base=controls/case;out.mkdir();source=lib/"model.tsv";n=native_n(source);result={}
    for label in ("identity","unsigned","signed"):
        ref=base/label;dest=out/label;dest.mkdir()
        target=source if label=="identity" else ref/"renamed.tsv"
        subprocess.run([tools/"select42",lib/"proof.bin",source,target,ref/"variables.tsv",ref/"declarations.txt",dest,str(n),str(n),"semantic"],check=True)
        new=catalog(dest)
        oracle=[tuple(map(int,(r[k] for k in ("flags","has_B","alive","mapped","selected")))) for r in table(ref/"catalog.tsv")]
        assert new==oracle and sum(v[-1] for v in new)==expected
        old_rows=(ref/"selected.tsv").read_text().splitlines()[1:]
        new_rows=(dest/"batch-rows.tsv").read_text().splitlines()
        assert [row.split()[1:] for row in old_rows]==[row.split()[1:] for row in new_rows]
        result[label]=keyed(dest/"transport.tsv")
    return result

def automatic(case,controls,tools,lib,out):
    base=controls/case;h=base/"hidden-d41";target=base/"signed/renamed.tsv"
    n=native_n(lib/"model.tsv");out.mkdir()
    subprocess.run([tools/"select42",lib/"proof.bin",lib/"model.tsv",target,h/"variables.tsv",h/"declarations.txt",out,str(n),str(n),"structure"],check=True)
    m=keyed(out/"transport.tsv");verified=premises(lib/"model.tsv",target,out,out)
    reason=Counter();residual=Counter()
    pending={int(r["variable"]) for r in table(out/"effective-map.tsv") if r["side"]=="0" and int(r["peer"])<0}
    for line in (h/"variables.tsv").open():
        side,v,p,role,why,_=line.split()
        if side=="0" and int(p)<0:
            reason[why.partition(":")[0]]+=1
            if int(v) in pending:residual[why.partition(":")[0]]+=1
    return dict(transport=m,verified=verified,remaining_seed_reasons=reason,unresolved_after_structure=residual,variables=n-1,oracle_table_supplied=False)

def check_case(case,a,out):
    base=a.functional/case/"1"; old=base/"reference/P0/native";light=base/"record/P0/native"
    p1=lambda mode:base/mode/"P1/native"
    eq=subprocess.check_output([a.tools/"support-check",old/"proof.bin",light/"proof.bin"],text=True)
    (out/"equivalence.tsv").write_text(eq);e=numbers(out/"equivalence.tsv")
    hist=check_history(light);assert hist==check_history(old) and len(hist)==e["births"]
    term_keys={}
    assert model_rows(old/"model.tsv",term_keys)==model_rows(light/"model.tsv",term_keys),(case,"model correspondence")
    counts={}
    for left,right in (("Reference","Light-only"),("Mapping-only","Combined"),("Combined","record-cold"),("record-cold","reuse")):
        ref,peer=p1(left),p1(right)
        assert catalog(ref)==catalog(peer) and (ref/"batch-rows.tsv").read_bytes()==(peer/"batch-rows.tsv").read_bytes()
        if left=="record-cold":assert (ref/"ready.tsv").read_bytes()==(peer/"ready.tsv").read_bytes()
    baseline=a.historical/case/"D41/P1/native" if case=="fib-snapshot-11" else a.d41_matrix/case/"AB/P1/native"
    legacy=[tuple(map(int,(r[k] for k in ("flags","has_B","alive","mapped","selected")))) for r in table(baseline/"catalog.tsv")]
    assert legacy==catalog(p1("Reference")),(case,"fixed D4.1 reference")
    def chosen(arm):return {i for i,(_,_,_,_,v) in enumerate(catalog(p1(arm)),1) if v}
    original,new=chosen("Reference"),chosen("Combined")
    assert original<=new,(case,"lost old candidates",original-new)
    added=new-original
    seen={}
    for arm in ("Reference","Light-only","Mapping-only","Combined","record-cold","reuse"):seen[arm]=imports(p1(arm))
    assert not seen["record-cold"]
    obs=a.observer if case=="fib-snapshot-11" else a.d41_audit/case
    native=verify(old/"proof.bin",obs/"native-theory.tsv")
    verify_inputs=premises(old/"model.tsv",p1("Combined")/"boundary.tsv",p1("Combined"),out)
    subprocess.run([a.tests/"d4/check",old/"proof.bin",out/"inputs",out/"map",obs/"native-learns.tsv",
                    p1("Combined")/"delta/declarations.txt",out],check=True)
    expected={int(r["native_id"]):int(r["ordinal"]) for r in table(p1("Mapping-only")/"catalog42.tsv")}
    independent=[[expected[int(r[0])],*map(int,r[1:])] for r in (l.split() for l in (out/"survivors.tsv").open())]
    actual=[[int(r[0]),*map(int,r[3:])] for r in (l.split() for l in (p1("Combined")/"batch-rows.tsv").open())]
    assert independent==actual,(case,"replay and transport differ")
    result=dict(equivalence=e,native_reason_checks=native,independent=numbers(out/"metrics.tsv"),premises=verify_inputs,
        births=e["births"],resident=sum(x[-1] for x in hist),baseline=len(original),combined=len(new),
        added=sorted(added),added_hits=sorted(added&seen["reuse"]),all_import_hits=len(seen["Combined"]),main_hits=len(seen["reuse"]))
    from witness42 import example,airline
    new_hits=sorted(added & seen["reuse"] & seen["Mapping-only"])
    if new_hits:
        proof=example(old,p1("Mapping-only"),new_hits[0]);save(out/"new-used-witness.json",proof)
        result["new_used_witness"]=new_hits[0]
    if case=="airline_reservations_6":result["events"]=airline(old,p1("Combined"),BASE/"bench"/case,out)
    if case!="fib-snapshot-11":
        result["A3"]=automatic(case,a.controls,a.tools,light,out/"hidden")
        control=read(a.controls/"identity-controls.json")[case]
        result["A1_A2"]=dict(fixture=control,light=controlled(case,a.controls,a.tools,light,out/"controlled",control["identity"]["eligible"]))
    return result

def model_rows(p,term_keys):
    import hashlib
    from urllib.parse import unquote_to_bytes
    work=str((p.parent.parent/"work").resolve()).encode()
    def canonical(raw):
        if work not in raw:return raw
        if raw==work:return b"<working_directory>"
        at=0;parts=[]
        while at<len(raw):
            sep=raw.find(b":",at)
            if sep<at or not raw[at:sep].isdigit():raise ValueError("unrecognized variable path in static shape")
            end=sep+1+int(raw[at:sep]);assert end<=len(raw)
            item=canonical(raw[sep+1:end]);parts.append(str(len(item)).encode()+b":"+item);at=end
        return b"".join(parts)
    h=hashlib.sha256();unordered=[];local={}
    with p.open("rb") as f:
        for l in f:
            if l.startswith(b"TERM\t"):
                _,ordinal,op,typ,data,*args=l.rstrip(b"\n").split(b"\t")
                key=(op,typ,data,tuple(local[x] for x in args))
                canonical_id=term_keys.setdefault(key,len(term_keys)+1)
                assert ordinal not in local
                local[ordinal]=canonical_id
                unordered.append(b"TERM\t"+str(canonical_id).encode()+b"\n");continue
            if l.startswith((b"H\t",b"VALUE_DEF\t")):
                tag,name,term=l.rstrip(b"\n").split(b"\t")
                unordered.append(b"\t".join([tag,name,str(local[term]).encode()])+b"\n");continue
            if l.startswith(b"SITE41\t"):
                tag,i,shape=l.rstrip(b"\n").split(b"\t")
                l=b"\t".join([tag,i,canonical(unquote_to_bytes(shape))])+b"\n"
            h.update(l)
    for l in sorted(unordered):h.update(l)
    return h.digest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ("functional","d41_matrix","d41_audit","controls","historical","observer","tools","tests","micro","out"):p.add_argument(n,type=Path)
    a=p.parse_args()
    for k,v in vars(a).items():setattr(a,k,v.resolve())
    a.out.mkdir(parents=True);res={}
    for case in load():
        dest=a.out/case;dest.mkdir();res[case]=check_case(case,a,dest)
        save(a.out/"dependency-equivalence.json",res);print("verified real native births",case,res[case]["births"],flush=True)
    for f in ("d4/results.json","triplets/results.json","light/results.json","libraries/results.json","lifetime/observations.txt","scope.txt","structure.txt"):
        assert (a.micro/f).stat().st_size>0,f
    plan=read(a.functional/"plan.json");assert sum(res[c]["baseline"] for c in list(load())[:3])==328
    assert len(read(a.functional/"properties.json"))==4*12
    gate=dict(L1="PASS",binary=plan["native"],tools=tool_hashes(a.tools),cases=list(res),
              births=sum(v["births"] for v in res.values()),checks=digest(a.out/"dependency-equivalence.json"),
              functional_properties=digest(a.functional/"properties.json"),micro=digest(a.micro/"light/results.json"),
              normal_clause_reproof_calls=0)
    save(a.out/"gate.json",gate)
if __name__=="__main__":main()
