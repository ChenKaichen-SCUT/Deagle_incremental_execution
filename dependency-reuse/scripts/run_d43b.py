"""Run the frozen, serial P0 matrix and seal each recorded library inside the reported cost."""
import argparse
import json
from pathlib import Path
import time
from cases42 import load
from run_stock import run, save
from d43_project_support import digest, check
from summarize_stock import interpret
from run_d42 import compare

MODES=("off","light-quality","light-no-quality","light-opaque","compact-opaque","compact")
DIAGNOSTICS=("off-trace","compact-audit")


def capture(exe,elf,case,spec,arm,directory):
    native=directory/"native"
    native.mkdir(parents=True,exist_ok=False)
    compact=arm.startswith("compact")
    legacy=arm.startswith("light") or arm=="compact-audit"
    args=["--d4-search-log",str(native/"search.tsv")]
    if arm!="off-default":
        args+=["--d1-manifest",str(native/"model.tsv"),"--d3-layouts","--d41-identities"]
    if compact:args+=["--d43-record",str(native/"dense.bin")]
    if legacy:args+=["--d3-proof",str(native/"proof.bin"),"--d41-triplets"]
    if arm.startswith("light"):
        args+=["--d42-light"]
        if arm!="light-quality":args+=["--d43-no-quality"]
    if arm in ("light-opaque","compact-opaque"):args+=["--d43-opaque-theory"]
    if arm in DIAGNOSTICS:args+=["--d43-boundaries",str(native/"boundaries.bin")]
    run(exe,{**spec,"argv":args+spec["argv"]},case,"P0",directory,elf)
    meta=json.loads((directory/"run.json").read_bytes())
    check(not meta["timed_out"] and meta["exit_code"] in (0,10),f"failed native run {case}/{arm}")
    needed=[]
    if compact:needed.append("dense.bin")
    if (native/"dense.bin.scoped").is_file():needed.append("dense.bin.scoped")
    if legacy:needed.append("proof.bin")
    if needed:needed.append("model.tsv")
    if (native/"proof.bin.quality.tsv").exists():needed.append("proof.bin.quality.tsv")
    start=time.monotonic_ns()
    files={name:dict(bytes=(native/name).stat().st_size,sha256=digest(native/name)) for name in needed}
    if needed:
        save(native/"library.json",dict(format="D43B-seal-v1",case=case,arm=arm,elf=elf,
                inputs=meta["input_sha256"],argv=args+spec["argv"],status=meta["exit_code"],files=files))
        (native/"library.sha256").write_text(digest(native/"library.json")+"\n")
    seal=time.monotonic_ns()-start if needed else 0
    result,_=interpret(meta,(directory/"stdout").read_text())
    save(directory/"result.json",result)
    kb=sum((native/name).stat().st_size for name in [*needed,"library.json","library.sha256"]) if needed else 0
    row=dict(case=case,arm=arm,process_ns=meta["wall_ns"],seal_ns=seal,total_ns=meta["wall_ns"]+seal,
             rss_kib=meta["peak_rss_kib"],library_bytes=kb,record_bytes=sum(files[n]["bytes"] for n in files if n!="model.tsv"),
             files=files,search_ns=sum(int(s.split()[0]) for s in (native/"search.tsv").read_text().splitlines()),
             result=result["target_status"],search=[q["native_cumulative"] for q in result["queries"]])
    save(directory/"cost.json",row)
    return row


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("binary",type=Path);p.add_argument("out",type=Path);p.add_argument("--case",action="append")
    p.add_argument("--modes",nargs="+",choices=(*MODES,*DIAGNOSTICS,"off-default"))
    a=p.parse_args();exe=a.binary.resolve();elf=digest(exe);root=a.out.resolve();cohort=load()
    for case in a.case or cohort:
        for arm in a.modes or (*MODES,"off-default",*DIAGNOSTICS):
            capture(exe,elf,case,cohort[case],arm,root/case/arm)
        if not a.modes:
            for arm in (*MODES,*DIAGNOSTICS):
                compare(root/case/"off",root/case/arm,True)
            check(digest(root/case/"off-trace/native/boundaries.bin")==digest(root/case/"compact-audit/native/boundaries.bin"),
                  case+" native reason/birth trace changed")
            check(digest(root/case/"compact/native/dense.bin")==digest(root/case/"compact-audit/native/dense.bin"),
                  case+" simultaneous Audit changed production library")


if __name__=="__main__":main()
