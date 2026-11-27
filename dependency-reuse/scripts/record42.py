"""Record an actual P0 on the frozen SC configuration, with either audit or light capture."""
import argparse
from pathlib import Path
import json,time
from cases42 import load
from diff_d1 import digest
from run_stock import run,save
from summarize_stock import interpret


def record(binary,case,mode,out,tools):
    from d42_prepare import tool_hashes
    if mode not in ("light","audit"):raise ValueError("unknown P0 recording mode")
    spec=dict(load()[case]);native=out/"native";native.mkdir(parents=True)
    opts=["--d3-layouts","--d41-identities","--d41-triplets","--d3-proof",str(native/"proof.bin"),"--d42-quality",
          "--d1-manifest",str(native/"model.tsv"),"--d4-search-log",str(native/"search.tsv")]
    if mode=="light":opts.append("--d42-light")
    spec["argv"]=[*opts,*spec["argv"]]
    run(binary,spec,case,"P0",out,digest(binary))
    meta=json.loads((out/"run.json").read_text())
    if meta["exit_code"] not in (0,10):raise RuntimeError("P0 failed: "+str(out))
    result,_=interpret(meta,(out/"stdout").read_text());save(out/"result.json",result)
    before=time.monotonic_ns();seal_cpu=time.process_time_ns()
    receipt=dict(format="D42-SC-v1",mode=mode,case=case,status=meta["exit_code"],elf=digest(binary),
                 inputs=meta["input_sha256"],argv=spec["argv"],tools=tool_hashes(tools),
                 files={f:digest(native/f) for f in ("proof.bin","model.tsv","proof.bin.quality.tsv")})
    save(native/"receipt42.json",receipt)
    (native/"receipt42.sha256").write_text(digest(native/"receipt42.json")+"\n")
    meta["seal_cpu_ns"]=time.process_time_ns()-seal_cpu
    meta["seal_ns"]=time.monotonic_ns()-before
    meta["inclusive_wall_ns"]=meta["wall_ns"]+meta["seal_ns"]
    save(out/"run.json",meta)
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("binary",type=Path);p.add_argument("out",type=Path)
    p.add_argument("--tools",required=True,type=Path)
    p.add_argument("--cases",nargs="+");p.add_argument("--modes",nargs="+",default=["light","audit"])
    a=p.parse_args()
    for c in a.cases or load():
        for m in a.modes:record(a.binary.resolve(),c,m,a.out.resolve()/c/m,a.tools.resolve())
