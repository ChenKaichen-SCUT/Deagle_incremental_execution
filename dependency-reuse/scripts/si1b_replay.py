"""Recompute maps, source witnesses and all independent passive streams using the published evidence."""
import argparse
import csv
import gc
import gzip
import hashlib
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from cases42 import load
from si1b_catalog import check, sha
from si1b_join import pipeline
from si1b_witness import verify

def check_passive(p):
    # All other events stay ordered. Replay only the originally measured iteration order of each Guard set.
    read=lambda x:json.loads(x.read_bytes())
    gold=read(p/"receipt.json")
    raw=p/"original.tsv.gz";blocks={};guard=None
    with gzip.open(raw,"rb") as f:
        for l in f:
            if l.startswith(b"[\t"):
                guard=l.rstrip(b"\n").split(b"\t",1)[1];blocks[guard]=[]
            elif l==b"]\n":guard=None
            elif guard is not None:blocks[guard].append(l)
    # K includes the miss/hit flag, canonical same-run binding handle, opcode and current atom count.
    for mode in ("original","off","shadow"):
        order=[v.encode() for v in read(p/mode/"guard-order.json")]
        check(len(order)==len(blocks) and set(order)==blocks.keys(),"guard directory")
        hashes={k:hashlib.sha256() for k in gold[mode]["streams"]};i=0;inside=False
        with gzip.open(raw,"rb") as f:
            for line in f:
                if line.startswith(b"[\t"):
                    inside=True
                    for hit in blocks[order[i]]:hashes["K"].update(hit)
                    i+=1
                elif line==b"]\n":inside=False
                elif not inside:hashes[line.split(b"\t",1)[0].decode()].update(line)
        check({k:v.hexdigest() for k,v in hashes.items()}==gold[mode]["streams"],"ordered passive replay")
    return len(blocks)

def run(evidence):
    files=json.loads((evidence/"files.json").read_bytes())
    for rel,item in files.items():
        p=evidence/rel;check(p.stat().st_size==item["bytes"] and sha(p)==item["sha256"],"integrity: "+rel)
    checks={}
    for case in load():
        root=evidence/case
        with TemporaryDirectory() as temp:
            t=Path(temp)
            for i,side in enumerate(("P0","P1")):
                p=t/side;p.mkdir();src=root/"native"/side/"shadow";shutil.copyfile(src/"seal.json",p/"seal.json")
                with gzip.open(src/"native.bin.gz","rb") as raw,(p/"native.bin").open("wb") as dst:shutil.copyfileobj(raw,dst)
            j=pipeline([t/"P0",t/"P1"],root/"source",t/"direct")
            count=len(j.mu);del j;gc.collect()
            compiled=("direct-map.tsv.gz","typed-keys.json.gz","P0-ir.json.gz","P1-ir.json.gz","P0-atoms.tsv.gz","P1-atoms.tsv.gz")
            check(all(sha(t/"direct"/n)==sha(root/"join"/n) for n in compiled),"recomputed artifacts differ: "+case)
            proof=verify(t,root/"source",t/"direct")
            check(proof==json.loads((root/"audit/witness-audit.json").read_bytes()),"source witnesses differ")
            checks[case]=dict(accepted=count,incorrect=proof["wrong"],recomputed_tables=list(compiled),
                passive_guard_events=[check_passive(root/"passive"/side) for side in ("P0","P1")])
        gc.collect()
    return dict(phase="SI-1B",verified_files=len(files),integrity=True,cases=checks)
if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("evidence",type=Path)
    print(json.dumps(run(p.parse_args().evidence),indent=2))
