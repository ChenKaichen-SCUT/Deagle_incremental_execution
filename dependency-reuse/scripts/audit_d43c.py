"""Bind C observations to the immutable B dual capture, then independently audit every native boundary."""
import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path
from audit_d43b import Library, seals
from cases42 import load
from d43_owner_probe import stream_receipt
from d43_project_support import check, digest, save
from run_d42 import compare
from run_stock import BASE

B_EVIDENCE = BASE / "reports/evidence/d43b"
B_INDEX_SHA = "4468d5f2acb74072c8a8743797587e2f47f1372d5456dbdf0455c66b447ebccb"


def slots(library, path):
    with path.open("w") as out:
        for fact, (index, group) in library.t.items():
            print(*fact, library.slots[1][group], int(library.observed(1, index)), file=out)


def proof_fingerprint(path):
    # Ignore exactly three elapsed-time words in the full Audit footer. Hash every graph byte.
    tail = 18*8+8
    h = hashlib.sha256()
    with path.open("rb") as f:
        left = path.stat().st_size-tail
        check(left>0, "short native Audit archive")
        while left:
            data=f.read(min(1<<20,left));check(data,"truncated graph");h.update(data);left-=len(data)
        footer=bytearray(f.read())
        check(len(footer)==tail and footer[-4:]==b"END3","Audit footer")
        clocks={str(i):struct.unpack_from("<Q",footer,8*i)[0] for i in (5,14,15)}
        for i in clocks:struct.pack_into("<Q",footer,8*int(i),0)
        h.update(footer)
    return h.hexdigest(),clocks


def run_checker(exe,proof,decl,slot,trace,side):
    result=subprocess.run([exe,proof,decl,slot,trace,side],check=True,capture_output=True,text=True)
    return {key:int(n) for key,n in (line.split() for line in result.stdout.splitlines())}


def review(case, old, new, d42, exe, out, index):
    directory=out/case;directory.mkdir(parents=True,exist_ok=True)
    before=old/case/"compact-audit";after=new/case/"compact-audit"
    p=before/"native";q=after/"native"
    for f in ("proof.bin","boundaries.bin","dense.bin","dense.bin.scoped","model.tsv"):
        check(digest(p/f)==index[f"accepted/{case}/compact-audit/native/{f}"]["sha256"],"wrong fixed B file "+f)
    for f in ("boundaries.bin","dense.bin","dense.bin.scoped"):
        check(digest(p/f)==digest(q/f),case+" changed the B record "+f)
    seals(after)
    def model(x):
        return stream_receipt(x/"native/model.tsv",Path(json.loads((x/"run.json").read_bytes())["cwd"]))["canonical_sha256"]
    check(model(before)==model(after),"C model changed")
    fields=compare(before,after,True)
    original,old_clocks=proof_fingerprint(p/"proof.bin")
    current,new_clocks=proof_fingerprint(q/"proof.bin")
    check(original==current,"full Audit graph, results or deterministic counters changed")
    slots(Library(p/"dense.bin"),directory/"T-slots.tsv")
    decl=d42/"functional"/case/"1/Mapping-only/P1/native/delta/declarations.txt"
    counts=run_checker(exe,q/"proof.bin",decl,directory/"T-slots.tsv",p/"boundaries.bin",q/"boundaries.bin.cert")
    prior=json.loads((B_EVIDENCE/"cases"/case/"audit.json").read_bytes())
    result=dict(case=case,boundaries=counts,proof_graph_fingerprint=original,B_clocks=old_clocks,C_clocks=new_clocks,
                same_full_Audit_except_three_clocks=True,same_dense_and_scoped=True,same_native_trace=True,
                inherited_births=prior["birth_check"],inherited_actual_leaves=prior["counts"],
                confirmed_born=prior["stats"]["births"],compact_eligible=prior["eligible"],
                properties=fields,sidecar_sha256=digest(q/"boundaries.bin.cert"))
    save(directory/"audit.json",result)
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ("B_matrix","C_matrix","D42","checker","output"):p.add_argument(arg,type=Path)
    p.add_argument("--case",action="append")
    a=p.parse_args();ix=B_EVIDENCE/"raw/files.json";check(digest(ix)==B_INDEX_SHA,"B index")
    index=json.loads(ix.read_bytes())["files"]
    rows=[review(c,a.B_matrix,a.C_matrix,a.D42,a.checker,a.output,index) for c in a.case or load()]
    save(a.output/"audit.json",rows)
