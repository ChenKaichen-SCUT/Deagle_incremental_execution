"""Bind P0 proof occurrences to the reviewed D1 manifests and their exact clause deltas."""
import argparse
from pathlib import Path
import gzip
import hashlib
import json
from itertools import zip_longest

from run_d1 import CASES
from run_stock import BASE, save


def fields(path):
    with gzip.open(path,"rt") as f:
        for line in f: yield line.split()


def metadata(pair):
    var={}
    for side,i,peer,role,why,anchor in fields(pair/"variables.tsv.gz"):
        if side=="1": break
        var[int(i)]=(int(peer),role,why)
    matched={int(leaf) for leaf,scope,n0,n1 in fields(pair/"clause-counts.tsv.gz") if int(n1)}
    return var,matched


def occurrences(pair):
    for s,seq,scope,leaf,why in fields(pair/"occurrences.tsv.gz"):
        if s=="1": break
        yield int(seq),scope,int(leaf),why


def self_occurrences(pair):
    packed=pair/"P0-comparability.gz"
    if not packed.exists():
        yield from occurrences(pair)
        return
    with gzip.open(packed,"rb") as f:
        seq=0
        for block in iter(lambda:f.read(1<<18),b""):
            for code in block:
                seq+=1
                yield seq,"BQU"[code//2],code&1,""


def clauses(native):
    with gzip.open(native,"rt") as f:
        for line in f:
            if line.startswith("C\t"):
                tag,scope,*lits=line.split()
                yield scope,list(map(int,lits))


def prepare(case,out,self_root=None,*,pair=None,native=None):
    d1=BASE/"reports/evidence/d1"
    pair=pair or d1/"pairs"/case
    native=native or d1/"runs/record"/case/"P0/native.tsv.gz"
    var,matched=metadata(pair)
    expected=json.loads((pair/"summary.json").read_text())["native_sha256"][0]
    h=hashlib.sha256()
    with gzip.open(native,"rb") as f:
        for block in iter(lambda:f.read(1<<20),b""):h.update(block)
    if h.hexdigest()!=expected:raise ValueError("D1 manifest checksum")
    out.mkdir(parents=True,exist_ok=False)
    with (out/"mapped.txt").open("w") as f:
        for v,(peer,*_) in var.items():
            if peer>=0:f.write(f"{v} {peer}\n")
    self_rows=self_occurrences(self_root/case) if self_root else None
    if self_root and json.loads((self_root/case/"summary.json").read_text())["native_sha256"]!=[expected,expected]:
        raise ValueError("self comparison uses different input")
    with (out/"inputs.txt").open("w") as f:
        for n,(occ,raw) in enumerate(zip_longest(occurrences(pair),clauses(native)),1):
            seq,scope,key,why=occ
            other,lits=raw
            if n!=seq or scope!=other:raise ValueError("D1 occurrence order")
            same=next(self_rows) if self_rows else None
            if same and same[:2]!=(seq,scope):raise ValueError("self occurrence order")
            if key: cause=0 if key in matched else 1
            else:
                cause=0
                for l in lits:
                    if l>=0 and var[l//2][0]<0:
                        cause|=2 if var[l//2][1]=="Aux" else 4
                if cause and same: cause |= 64 if not same[2] else 128
                if not cause and ((scope,why) not in (("U","unknown_origin"),("Q","query_scope_changed_or_unknown"))):
                    raise ValueError(("unmatched occurrence without a rejection witness",seq,scope,why))
            f.write(" ".join(map(str,[scope,cause,*lits]))+"\n")
    save(out/"receipt.json",dict(native_sha256=expected,occurrences=n,d1_delta_sha256=hashlib.sha256(
        (pair/"summary.json").read_bytes()).hexdigest()))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("new_directory",type=Path)
    p.add_argument("--self-diffs",type=Path)
    args=p.parse_args()
    for case in CASES:prepare(case,args.new_directory/case,args.self_diffs)
