"""One serial four-arm functional pass. Cold and reuse share one freshly sealed P0 per case."""
import argparse
import json
from pathlib import Path
import time
from cases42 import load
from d43_prepare import FORMAT, RULES, FILES, tool_hashes
from diff_d1 import digest
from run_d42 import compare
from run_stock import BASE, run, save
from summarize_stock import interpret


def read(path):
    return json.loads(path.read_bytes())


def run_one(exe,spec,case,side,folder,options,sha):
    if folder.exists() and (folder/"run.json").exists():
        raise ValueError("refusing to overwrite prior run")
    run(exe,{**spec,"argv":[*map(str,options),*spec["argv"]]},case,side,folder,sha)
    meta=read(folder/"run.json")
    if meta["timed_out"] or meta["exit_code"] not in (0,10):
        raise RuntimeError(f"native failure at {folder}: {meta['exit_code']}")
    result,_=interpret(meta,(folder/"stdout").read_text())
    save(folder/"result.json",result)
    return meta


def model(exe,spec,case,side,folder,sha,tools=None):
    n=folder/"native";n.mkdir(parents=True)
    opts=["--d4-search-log",n/"search.tsv","--d1-manifest",n/"model.tsv","--d3-layouts","--d41-identities"]
    if tools is not None:
        opts+=["--d43-record",n/"dense.bin"]
    meta=run_one(exe,spec,case,side,folder,opts,sha)
    if tools is not None:
        begin=time.monotonic_ns()
        files={f:dict(bytes=(n/f).stat().st_size,sha256=digest(n/f)) for f in sorted(FILES)}
        seal=dict(format=FORMAT,rules=RULES,mode="compact",capacities=[1024,1024],overflow=1023,
                  case=case,elf=sha,inputs=meta["input_sha256"],argv=meta["argv"][1:],
                  status=meta["exit_code"],tools=tool_hashes(tools),files=files)
        save(n/"library.json",seal)
        (n/"library.sha256").write_text(digest(n/"library.json")+"\n")
        meta["seal_ns"]=time.monotonic_ns()-begin
        save(folder/"run.json",meta)


def live(exe,tools,spec,case,folder,lib,mode,sha):
    begin=time.monotonic_ns()
    n=folder/"native";n.mkdir(parents=True)
    control=dict(case=case,library_sha256=(lib/"library.sha256").read_text().strip())
    if case=="airline_reservations_6":
        control["source_patch"]=dict(file="program.c",patch=str(BASE/"bench"/case/"patch.diff"),
            patch_sha256=spec["files_sha256"]["patch.diff"],new_sha256=spec["files_sha256"][spec["inputs"]["P1"]["program.c"]])
    save(n/"control43.json",control)
    setup=time.monotonic_ns()-begin
    opts=["--d43-load",lib,"--d4-mode",mode,"--d4-out",n,"--d4-tools",tools,
          "--d41-identities","--d4-search-log",n/"search.tsv"]
    meta=run_one(exe,spec,case,"P1",folder,opts,sha)
    meta["setup_ns"]=setup
    save(folder/"run.json",meta)
    for name in ("compact-delta.json","policy.json","imports.tsv","hits.tsv","cumulative-work.tsv"):
        if not (n/name).is_file():
            raise RuntimeError("missing live record "+name)


def matrix(exe,tools,root,cases,observer):
    specs=load();stock=read(BASE/"configs/build.json")
    upstream=Path(stock["binary_path"]);locked=stock["binary_sha256"];sha=digest(exe)
    if digest(upstream)!=locked:
        raise ValueError("stock ELF differs from frozen baseline")
    for case in cases or specs:
        spec=specs[case];out=root/case
        out.mkdir(parents=True,exist_ok=False)
        for side in ("P0","P1"):
            run_one(upstream,spec,case,side,out/"stock"/side,[],locked)
        for side in ("P0","P1"):
            model(exe,spec,case,side,out/"off"/side,sha)
        producer=out/"compact/P0"
        model(exe,spec,case,"P0",producer,sha,tools)
        live(exe,tools,spec,case,out/"compact-cold/P1",producer/"native","record-cold",sha)
        live(exe,tools,spec,case,out/"compact-reuse/P1",producer/"native","reuse",sha)
        checks={}
        for label,side,folder in (("off","P0",out/"off/P0"),("off","P1",out/"off/P1"),
                ("compact","P0",producer),("compact-cold","P1",out/"compact-cold/P1"),
                ("compact-reuse","P1",out/"compact-reuse/P1")):
            checks[label+"/"+side]=compare(out/"stock"/side,folder,False)
        compare(out/"off/P0",producer,True)
        compare(out/"off/P1",out/"compact-cold/P1",True)
        for file in ("ready.tsv","effective-map.tsv","births.tsv","eligible.tsv","input-matches.tsv","theory-matches.tsv"):
            if digest(out/"compact-cold/P1/native"/file)!=digest(out/"compact-reuse/P1/native"/file):
                raise RuntimeError("cold/reuse prep differs: "+file)
        if observer:
            for side in ("P0","P1"):
                folder=out/"stock-clock"/side
                run_one(observer,spec,case,side,folder,[],digest(observer))
                checks["stock-clock/"+side]=compare(out/"stock"/side,folder,True)
        save(out/"checks.json",checks)
        print(case,read(out/"compact-reuse/P1/native/policy.json")["chosen"],flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for key in ("binary","tools","output"):
        p.add_argument(key,type=Path)
    p.add_argument("--case",action="append")
    p.add_argument("--stock-clock",type=Path)
    a=p.parse_args()
    matrix(a.binary.resolve(),a.tools.resolve(),a.output.resolve(),a.case,a.stock_clock)
