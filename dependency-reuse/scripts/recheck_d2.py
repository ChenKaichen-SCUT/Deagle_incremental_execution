"""Replay an archived real D2 run from Git data and the standalone C++ checker."""
import argparse
import gzip
import hashlib
from pathlib import Path
import shutil
import struct
import tempfile
import json
import subprocess

from prepare_d2 import prepare
from run_stock import BASE


FOOTER_STATS=18


def logical_sha(path):
    size=path.stat().st_size
    stats_pos=size-8-FOOTER_STATS*8
    if stats_pos<12:raise ValueError("truncated archive")
    h=hashlib.sha256()
    with path.open("rb") as f:
        left=stats_pos
        while left:
            data=f.read(min(left,1<<20))
            if not data:raise ValueError("short proof")
            h.update(data);left-=len(data)
        tail=bytearray(f.read())
    clocks={}
    for i in (5,14,15):
        clocks[str(i)]=struct.unpack_from("<Q",tail,8*i)[0]
        struct.pack_into("<Q",tail,8*i,0)
    h.update(tail)
    return h.hexdigest(),clocks


def restore(ev,case,receipt,dest):
    with gzip.open(ev/"pairs"/case/receipt["compressed_payload"],"rb") as src,dest.open("xb") as dst:
        shutil.copyfileobj(src,dst,1<<20)
    with dest.open("r+b") as f:
        for i,n in receipt["footer_clocks"].items():
            f.seek(-8-FOOTER_STATS*8+8*int(i),2)
            f.write(struct.pack("<Q",n))
    with dest.open("rb") as f:
        h=hashlib.sha256()
        for b in iter(lambda:f.read(1<<20),b""):h.update(b)
    if h.hexdigest()!=receipt["raw_sha256"]:raise ValueError("restored proof digest mismatch")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("checker",type=Path);p.add_argument("case");p.add_argument("new_dir",type=Path)
    p.add_argument("--repeat",type=int,choices=(1,2,3),default=1)
    p.add_argument("--evidence",type=Path,default=BASE/"reports/evidence/d2")
    a=p.parse_args();ev=a.evidence.resolve();out=a.new_dir.resolve();out.mkdir(parents=True,exist_ok=False)
    receipt=json.loads((ev/"pairs"/a.case/"runs.json").read_text())["proofs"][a.repeat-1]
    with tempfile.TemporaryDirectory() as name:
        d=Path(name)
        restore(ev,a.case,receipt,d/"proof")
        prepare(a.case,d/"inputs",ev/"self")
        with gzip.open(ev/"pairs"/a.case/"native-learns.tsv.gz","rb") as src,(d/"oracle").open("wb") as dst:
            shutil.copyfileobj(src,dst)
        subprocess.run([a.checker.resolve(),d/"proof",d/"inputs/inputs.txt",d/"inputs/mapped.txt",d/"oracle",out],check=True)
    for file in ("learned.tsv","used.tsv","survivors.tsv"):
        with gzip.open(ev/"pairs"/a.case/(file+".gz"),"rb") as src:
            if hashlib.sha256(src.read()).digest()!=hashlib.sha256((out/file).read_bytes()).digest():
                raise ValueError(file+" does not reproduce")
    print(a.case,a.repeat,"verified")


if __name__=="__main__":main()
