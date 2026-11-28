"""Serial P1-only matrix. The unmodified binary calls an explicitly experimental worker at its existing first root."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import platform
import subprocess
import time

from cases42 import load
from run_d43d import run_one
from si1b_review_space import BASE,EVIDENCE,check,digest,read,save
from si1b_value_boundary import expected_args


def execute(binary,observer,root):
    specs=load()
    plan_path=BASE/"configs/si1b-value.json"
    plan=read(plan_path)
    frozen=EVIDENCE/"si1b-value/frozen"
    index=read(frozen/"batches.json")
    builds=read(EVIDENCE/"d43d/build.json")
    stock_path=Path(read(BASE/"configs/build.json")["binary_path"])
    paths={"stock":stock_path,"diagnostic":binary,"stock-clock":observer}
    hashes={arm:digest(path) for arm,path in paths.items()}
    check(hashes==dict(stock=builds["unmodified_stock_elf_sha256"],diagnostic=builds["production_elf_sha256"],
                       **{"stock-clock":builds["stock_clock_observer_elf_sha256"]}),"different binaries")
    check(digest(plan_path)==index["plan_sha256"],"plan mismatch")
    for case in plan["cases"]:
        check(digest(frozen/case/"seal.json")==index["seals"][case],"changed seal")
        seal=read(frozen/case/"seal.json")
        for arm in ("A","new"):
            check(digest(frozen/case/(arm+".ready.tsv"))==seal["batches"][arm]["sha256"],"changed selected batch")
        check(specs[case]["limits"]==seal["limits"],"limits changed")
    check(os.sched_getaffinity(0)>={0},"CPU 0 unavailable")
    os.sched_setaffinity(0,{0})
    root.mkdir(parents=True,exist_ok=False)
    tools=BASE/"diagnostics/si1b-value"
    lease=(root.parent/"timing.lock").open("a")
    fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    save(root/"environment.json",dict(cpu=sorted(os.sched_getaffinity(0)),kernel=platform.release(),binary_sha256=hashes,
        exact_binary_paths={k:str(v) for k,v in paths.items()},preregistered_plan_sha256=digest(plan_path),
        seals=index["seals"],clock=time.get_clock_info("monotonic").resolution,
        preflight_load=Path("/proc/loadavg").read_text().strip(),limits={k:specs[k]["limits"] for k in plan["cases"]},
        preflight_processes=subprocess.check_output(["ps","-eo","pid,psr,stat,comm"],text=True),P0_runs=0))
    schedule=[(n,c,arm) for n,order in enumerate(plan["round_orders"],1) for c in plan["cases"] for arm in order]
    schedule += [(n,c,"stock-clock") for n in range(1,4) for c in plan["cases"]]
    for n,c,arm in schedule:
        start=time.monotonic_ns()
        folder=root/c/str(n)/arm
        folder.mkdir(parents=True)
        spec=specs[c]
        sample=dict(case=c,round=n,arm=arm,start_ns=start)
        with (root/"starts.jsonl").open("a") as f:print(json.dumps(sample),file=f,flush=True)
        try:
            if arm in ("stock","stock-clock"):
                meta=run_one(paths[arm],spec,c,"P1",folder,[],hashes[arm])
                setup=0
            else:
                t=time.monotonic_ns()
                native=folder/"native"
                native.mkdir()
                lib=frozen/c
                save(native/"diagnostic-control.json",dict(format=index["format"],case=c,arm=arm))
                options=expected_args(lib,native,tools,arm,[])
                setup=time.monotonic_ns()-t
                meta=run_one(binary,spec,c,"P1",folder,options,hashes["diagnostic"])
                receipt=read(native/"diagnostic-receipt.json")
                check(receipt["arm"]==arm and receipt["seal_sha256"]==index["seals"][c],"missing validated boundary")
            sample.update(ok=True,process_ns=meta["wall_ns"],setup_ns=setup)
        except (ValueError,OSError,RuntimeError,AssertionError,KeyError) as error:
            sample.update(ok=False,error=f"{type(error).__name__}: {error}")
        sample["end_ns"]=time.monotonic_ns()
        save(folder/"outcome.json",sample)
        with (root/"schedule.jsonl").open("a") as f:print(json.dumps(sample),file=f,flush=True)
        print(n,c,arm,sample.get("error","complete"),flush=True)
    lease.close()


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for n in ("binary","observer","output"):p.add_argument(n,type=Path)
    a=p.parse_args();execute(a.binary.resolve(),a.observer.resolve(),a.output.resolve())
