"""One shadow solve per side. Model-only audit and small controls are separated from cost arms."""
import argparse
import csv
import difflib
import gzip
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import time

from cases42 import load
from run_stock import BASE, ENV, run, save, sha
from si1b_sources import source_pair


def inputs(spec,case):
    return {name:tuple((BASE/"bench"/case/spec["inputs"][v][name]).read_bytes() for v in ("P0","P1"))
            for name in spec["inputs"]["P0"]}

def emit_seal(native,folder,source,side):
    path=folder/"native.bin"
    start=time.monotonic_ns()
    seal=dict(version="SI1B-shadow-1",elf=sha(native),body=sha(path),bytes=path.stat().st_size,
              source_sha256=sha(source/"source-catalog.json"),tokens=sha(source/(side+".tokens")),
              abi_args=json.loads((folder/"run.json").read_text())["argv"],
              inputs=json.loads((folder/"run.json").read_text())["input_sha256"])
    save(folder/"seal.json",seal)
    return time.monotonic_ns()-start

def set_env(directory,src,side,mode):
    for k in list(ENV):
        if k.startswith("DEAGLE_SI1B_"):del ENV[k]
    if mode!="off":
        ENV["DEAGLE_SI1B_CATALOG"]=str(directory/"native.bin")
        ENV["DEAGLE_SI1B_TOKENS"]=str(src/(side+".tokens"))
        if mode=="audit":
            ENV["DEAGLE_SI1B_AUDIT"]="1"
            ENV["DEAGLE_SI1B_MODEL_ONLY"]="1"

def cohort(native,root,modes,cases):
    for case,spec in load().items():
        if cases and case not in cases:continue
        folder=root/case; src=folder/"source"
        if not src.exists():
            _,ns=source_pair(inputs(spec,case),BASE/"bench"/case/"patch.diff",src,32 if "--32" in spec["argv"] else 64)
            save(src/"time.json",dict(scan_inheritance_ns=ns))
        for mode in modes:
            for side in ("P0","P1"):
                out=folder/mode/side
                out.mkdir(parents=True,exist_ok=False)
                set_env(out,src,side,mode)
                args=["--d4-search-log",str(out/"search.tsv")]
                if mode=="audit":
                    args+=["--d1-manifest",str(out/"model.tsv"),"--d3-layouts","--d41-identities"]
                run(native,dict(spec,argv=args+spec["argv"]),case,side,out,sha(native))
                meta=json.loads((out/"run.json").read_text())
                if meta["exit_code"] not in ((77,) if mode=="audit" else (0,10)) or meta["timed_out"]:
                    raise RuntimeError(str(out))
                if mode!="off":
                    save(out/"seal-time.json",dict(seal_ns=emit_seal(native,out,src,side)))

def control(native,root):
    path=BASE/"tests/si1b/identity.c"; old=path.read_bytes()
    new=old.replace(b"static unsigned a, b, sink;",b"static volatile unsigned unrelated;\nstatic unsigned a, b, sink;")
    new=new.replace(b"  b = nondet_uint();",b"  unrelated = nondet_uint();\n  b = nondet_uint();")
    new=new.replace(b"  sink = a;\n  repeated();",b"  sink = a;")
    patch=b"".join(difflib.diff_bytes(difflib.unified_diff,old.splitlines(True),new.splitlines(True),
                                      fromfile=b"a/model.c",tofile=b"b/model.c"))
    root.mkdir(parents=True,exist_ok=False); (root/"edit.patch").write_bytes(patch)
    source_pair({"model.c":(old,new)},root/"edit.patch",root/"source",32)
    for side,which,code in (("P0","P0",old),("P1","P1",new),("same-cwd-control","P0",old)):
        out=root/side;work=out/"work";work.mkdir(parents=True)
        (work/"model.c").write_bytes(code); set_env(out,root/"source",which,"audit")
        args=[str(native),"--d1-manifest",str(out/"model.tsv"),"--d3-layouts","--d41-identities",
              "--function","main","--deagle-closure","--mm","sc","--32","--unwind","4",
              "--unwinding-assertions","--json-ui","model.c"]
        with (out/"stdout").open("wb") as log,(out/"stderr").open("wb") as err:
            rc=subprocess.run(args,cwd=work,env=ENV,stdout=log,stderr=err,timeout=60).returncode
        save(out/"run.json",dict(argv=args,cwd=str(work),exit_code=rc,input_sha256={"model.c":sha(work/"model.c")}))
        if rc!=77:raise RuntimeError(str(out))
        emit_seal(native,out,root/"source",which)
if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action",choices=["control","cohort"]);p.add_argument("native",type=Path);p.add_argument("out",type=Path)
    p.add_argument("--modes",nargs="+",choices=["off","shadow","audit"],default=["off","shadow","audit"])
    p.add_argument("--cases",nargs="*");a=p.parse_args();binary=a.native.resolve();root=a.out.resolve()
    if a.action=="control":control(binary,root)
    else:cohort(binary,root,a.modes,a.cases)
