"""Read the sealed native library and compare actual tags and UsedLeaf against independent full Audit."""
import argparse
from array import array
from collections import Counter
import csv
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import struct
import subprocess

from d43b_dense import A,CASES,leaf_rows,reference
from d43_project_support import check,digest,save,signed_map,translated,zipped
from d43_owner_probe import stream_receipt
from d43_review import write_tsv
from run_d42 import compare
from run_d43b import MODES,DIAGNOSTICS


class Library:
    def __init__(self,path):
        self.data=path.read_bytes();self.pos=0;self.offsets=array("I")
        self.magic=self.take(8)
        check(self.magic in (b"D43DNS1\0",b"D43DNS2\0") and self.get("<III")== (0x01020304,1024,1023),"compact format")
        while True:
            mark=self.take(1)
            if mark==b"D":break
            self.offsets.append(self.pos-1)
            if mark==b"S":
                i,flags=self.get("<IB")
                check(self.magic==b"D43DNS2\0" and i==len(self.offsets) and flags<16 and flags&12,"invalid scope disposition")
                continue
            check(mark==b"L","unknown frame")
            i,n,flags=self.get("<IIB")
            check(i==len(self.offsets) and flags<16,"birth ordinal or scope")
            check(self.magic!=b"D43DNS2\0" or not flags&12,"scoped payload in production library")
            self.skip(4*n+256)
        self.keys=[];self.slots=[]
        for d in ("B","T"):
            keys=[];slots=[]
            for i in range(self.word()):
                slot,sz=self.get("<HI");key=self.take(sz).decode()
                check(slot==min(i,1023) and json.loads(key)[0]==d,"persisted slot/domain")
                keys.append(key);slots.append(slot)
            check(len(set(keys))==len(keys),"duplicate full group key")
            self.keys.append(keys);self.slots.append(slots)
        self.b=array("I");self.b.frombytes(self.take(4*self.word()))
        self.t={}
        for i in range(self.word()):
            *fact,g=self.get("<4iI");fact=tuple(fact)
            check(fact not in self.t and g<len(self.keys[1]),"invalid native declaration")
            self.t[fact]=(i,g)
        self.bits=[]
        for n in (len(self.b),len(self.t)):
            nb=self.word();check(nb==(n+7)//8,"UsedLeaf length")
            bits=self.take(nb)
            check(not n%8 or not bits[-1]>>(n%8),"invalid UsedLeaf padding")
            self.bits.append(bits)
        check(self.word()==len(self.offsets),"incomplete birth directory")
        self.exit=self.word()
        check(self.exit in (0,10) and self.take(8)==b"ENDDENSE" and self.pos==len(self.data),"invalid footer")

    def skip(self,n):
        self.pos+=n
        check(self.pos<=len(self.data),"truncated compact archive")
    def take(self,n):
        start=self.pos;self.skip(n);return self.data[start:self.pos]
    def get(self,fmt):return struct.unpack(fmt,self.take(struct.calcsize(fmt)))
    def word(self):return self.get("<I")[0]
    def observed(self,d,index):return bool(self.bits[d][index//8]&(1<<(index%8)))
    def births(self, scoped=None):
        side=scoped.read_bytes() if scoped and scoped.exists() else None
        pos=8;scopes=0
        if side:check(side[:8]==b"D43SCP1\0","scoped Audit header")
        for at in self.offsets:
            stream=self.data
            if stream[at:at+1]==b"S":
                ordinal,scope=struct.unpack_from("<IB",stream,at+1)
                if side is None:
                    yield ordinal,scope,None,None,None
                    continue
                at=pos;stream=side;scopes+=1
                check(stream[at:at+1]==b"L","missing scoped Audit record")
                j,n,k=struct.unpack_from("<IIB",stream,at+1)
                check((j,k)==(ordinal,scope),"wrong scoped Audit record")
                pos+=10+4*n+256
            i,n,flags=struct.unpack_from("<IIB",stream,at+1)
            at+=10;mid=at+4*n
            yield i,flags,stream[at:mid],int.from_bytes(stream[mid:mid+128],"little"),int.from_bytes(stream[mid+128:mid+256],"little")
        if side:check(side[pos:]==b"ENDSCOP1"+struct.pack("<I",scopes),"scoped Audit footer")


def mark_dirty(dirty, slot, observed, preserved):
    # An overflow slot represents every key assigned past the capacity, including
    # registered members whose individual bit was never observed.
    if not preserved and (observed or slot == 1023):
        dirty.add(slot)


def seals(directory):
    native=directory/"native"
    s=native/"library.json"
    check(digest(s)==(native/"library.sha256").read_text().strip(),"library envelope")
    rec=json.loads(s.read_bytes())
    for name,r in rec["files"].items():
        path=native/name
        check(path.stat().st_size==r["bytes"] and digest(path)==r["sha256"],"library file integrity")
    return rec


def review_case(case,matrix,d42,preflight,engine,out):
    case_dir=matrix/case;dir0=case_dir/"compact";dir_dual=case_dir/"compact-audit"
    old=d42/"functional"/case/"1/reference/P0"
    new=d42/"functional"/case/"1/Mapping-only/P1/native"
    p=A/"cases"/case
    oracle=json.loads((p/"inputs.json").read_bytes())
    for arm in (*MODES,*DIAGNOSTICS):
        compare(case_dir/"off",case_dir/arm,True)
    # SITE41 contains the original capture directory even after an evidence restore.
    def canonical_model(folder):
        captured_cwd=Path(json.loads((folder/"run.json").read_bytes())["cwd"])
        return stream_receipt(folder/"native/model.tsv",captured_cwd)["canonical_sha256"]
    same_model=canonical_model(old)
    for arm in ("off","compact","compact-audit"):
        folder=case_dir/arm
        check(same_model==canonical_model(folder),
              case+"/"+arm+" fixed model/encoding mismatch")
    pair=compare(d42/"functional"/case/"1/stock/P0",dir0,False)
    compare(d42/"functional"/case/"1/stock/P0",case_dir/"off-default",True)
    seal=seals(dir0);seals(dir_dual)
    check(digest(dir0/"native/dense.bin")==digest(dir_dual/"native/dense.bin"),"dual changed native compact library")
    trace=digest(case_dir/"off-trace/native/boundaries.bin")
    check(trace==digest(dir_dual/"native/boundaries.bin"),"off/dense boundary stream differs")
    check(seal["elf"]==json.loads((dir0/"run.json").read_bytes())["binary_sha256"],"ELF binding")
    lib=Library(dir0/"native/dense.bin")
    cols=[{},{}]
    with gzip.open(p/"groups.tsv.gz","rt") as f:
        for r in csv.DictReader(f,delimiter="\t"):
            key=r["canonical_key"];cols[int(json.loads(key)[0]=="T")][int(r["id"])]=key
    key_ids=[{k:i for i,k in enumerate(keys)} for keys in lib.keys]
    check([set(m) for m in key_ids]==[set(m.values()) for m in cols],"native full group key set")
    actual=Counter();dirty=[set(),set()];exact=Counter()
    raw=bytearray((preflight/case/"dense-leaves.bin").read_bytes());nb,nt=struct.unpack_from("<II",raw,8)
    check((nb,nt)==(len(lib.b),len(lib.t)),"actual registry cardinality")
    for j,(d,leaf,(gid,slot,state,reached)) in enumerate(leaf_rows(raw)):
        if d==0:
            ix=leaf-1;local=lib.b[ix]
        else:
            ix,local=lib.t[leaf]
        observed=lib.observed(d,ix)
        if state>=5:
            check(d==0 and not observed and local==(0xffffffff if state==5 else 0xfffffffe),"query/unknown in permanent U")
            continue
        key=cols[d][gid]
        check(local==key_ids[d][key],"actual premise/group mismatch")
        native_slot=lib.slots[d][local]
        pos=16+8*j if not d else 16+8*nb+24*(j-nb)+16
        struct.pack_into("<H",raw,pos+4,native_slot)
        lab=("B","T")[d];actual["registered_"+lab]+=1
        if reached&2:actual["permanent_support_"+lab]+=1
        check(not reached&2 or observed,"exportable Audit support leaf missing from UsedLeaf")
        mark_dirty(dirty[d],native_slot,observed,state==0)
        if observed:
            actual["observed_"+lab]+=1
            if state:actual["dirty_leaves_"+lab]+=1
    case_out=out/case;case_out.mkdir(parents=True,exist_ok=True)
    tmp=case_out/"reference-directory.bin";tmp.write_bytes(raw)
    expected=case_out/"same-run-reference.bin"
    subprocess.run([engine,dir_dual/"native/proof.bin",tmp,expected],check=True)
    tmp.unlink()
    mu=signed_map(new/"effective-map.tsv")
    dmask=[sum(1<<s for s in v) for v in dirty]
    with (A/"summary/candidates.tsv").open() as f:
        hist={int(r["ordinal"]):(r["class"],int(r["previous_hit"])) for r in csv.DictReader(f,delimiter="\t") if r["case"]==case}
    kept=[];tag_compare=Counter();previous_hits=Counter()
    with gzip.open(p/"births.tsv.gz","rt") as inf,zipped(case_out/"birth-check.tsv.gz") as data:
        data.write(b"ordinal\taudit_id\tflags\tclass\ttranslated\texact\teligible\tB_intersects\tT_intersects\textra_B_bits\textra_T_bits\n")
        for ref,native,prior in zip(reference(expected),lib.births(dir_dual/"native/dense.bin.scoped"),csv.DictReader(inf,delimiter="\t"),strict=True):
            i,flags,node,lits,b,t=ref;j,tag,conclusion,x,y=native
            check(i==j==int(prior["ordinal"]) and node==int(prior["audit_id"]) and conclusion==lits,"learned literal mismatch")
            wanted=int(bool(b))+2*int(bool(t))+4*int(bool(flags&2))+8*int(bool(flags&5))
            check(tag==wanted and not (b&~x or t&~y),"scope/class or missing native support bit")
            tag_compare["all_births"]+=1
            tag_compare["equal_tags"]+=int((x,y)==(b,t))
            tag_compare["superset_tags"]+=int((x,y)!=(b,t))
            mapped=all((translated(l,mu) or 0)>=2 for (l,) in struct.iter_unpack("<i",lits))
            check(mapped==(prior["mapped"]=="1"),"conclusion mapping disagrees with D4.2")
            scope=tag&12;fam="UNKNOWN" if tag&8 else "QUERY" if tag&4 else "M" if tag&3==3 else "T" if tag&2 else "B"
            dead_b=bool(x&dmask[0]);dead_t=bool(y&dmask[1])
            eligible=not scope and mapped and not dead_b and not dead_t
            ref_ok=i in hist
            if ref_ok:exact[fam]+=1
            check(not eligible or ref_ok,"dense false admission")
            if eligible:
                kept.append((i,fam));previous_hits[fam]+=hist[i][1]
            data.write(f"{i}\t{node}\t{tag}\t{fam}\t{int(mapped)}\t{int(ref_ok)}\t{int(eligible)}\t{int(dead_b)}\t{int(dead_t)}\t{(x&~b).bit_count()}\t{(y&~t).bit_count()}\n".encode())
    same_ref=digest(expected);expected.unlink()
    stats={k:int(v) for k,v in (line.split() for line in (dir0/"native/dense.bin.stats").read_text().splitlines())}
    for k in ("proof_nodes","proof_parent_edges","duplicate_condition_nodes","SupportStore_instances","legacy_recorders","legacy_quality_enabled"):
        check(stats[k]==0,k+" ran during compact production")
    check(stats["births"]==sum(1 for _ in lib.offsets),"recorded birth denominator")
    result=dict(case=case,counts=actual,registered_groups=[len(m) for m in lib.keys],
                overflow_groups=[max(0,len(m)-1023) for m in lib.keys],dirty_slots=list(map(len,dirty)),
                exact=dict(exact),eligible=dict(Counter(f for _,f in kept)),previously_hit=dict(previous_hits),
                birth_check=tag_compare,candidate_subset_violations=0,permanent_union_missing=0,
                same_run_reference_sha256=same_ref,model_canonical_sha256=same_model,boundary_stream_sha256=trace,
                P0_properties_and_witnesses=pair,stats=stats,
                projection_confirmed=oracle["universe"]["auditB"]==actual["permanent_support_B"] and
                                     oracle["universe"]["auditT"]==actual["permanent_support_T"])
    check(result["projection_confirmed"],"A permanent union differs")
    write_tsv(case_out/"eligible.tsv",["ordinal","class","D42_hit"],((i,f,hist[i][1]) for i,f in kept))
    save(case_out/"audit.json",result)
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("matrix","d42","preflight","reference_engine","out"):p.add_argument(k,type=Path)
    p.add_argument("--case",action="append")
    a=p.parse_args();a.d42=a.d42.resolve();a.matrix=a.matrix.resolve();a.out.mkdir(parents=True,exist_ok=True)
    results=[review_case(c,a.matrix,a.d42,a.preflight,a.reference_engine,a.out) for c in a.case or CASES]
    save(a.out/"audit.json",results)
