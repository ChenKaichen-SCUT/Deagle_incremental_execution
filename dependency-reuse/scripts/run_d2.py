"""Run frozen P0s on CPU 0; predeclare every run before starting the first one."""
import argparse
import json
from pathlib import Path

from run_stock import BASE,run,sha,save
from run_d1 import CASES
from summarize_stock import interpret


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("binary",type=Path)
    p.add_argument("oracle",type=Path)
    p.add_argument("new_directory",type=Path)
    p.add_argument("--pilot",action="store_true")
    args=p.parse_args()
    binary,oracle,root=args.binary.resolve(),args.oracle.resolve(),args.new_directory.resolve()
    root.mkdir(parents=True,exist_ok=False)
    lock=BASE/"bench/manifest.json"
    specs=json.loads(lock.read_text())
    binaries=[sha(binary),sha(oracle)]
    schedule=[]
    for i,case in enumerate(CASES):
        for rep in range(1 if args.pilot else 3):
            modes=["off","on"] if (rep+i)%2==0 else ["on","off"]
            for mode in modes: schedule.append((case,rep+1,mode))
        schedule.append((case,1,"oracle"))
    save(root/"plan.json",dict(schedule=schedule,binary_sha256=binaries[0],oracle_sha256=binaries[1],
        frozen_lock_sha256=sha(lock),cpu=0,serial=True,cold="new process/model/solver; OS cache unmanaged"))
    for case,rep,mode in schedule:
        dest=root/case/f"{mode}-{rep}"
        spec=dict(specs[case])
        if mode=="on":spec["argv"]=["--d2-proof",str(dest/"knowledge.bin"),*spec["argv"]]
        probe=mode=="oracle"
        run(oracle if probe else binary,spec,case,"P0",dest,binaries[int(probe)])
        meta=json.loads((dest/"run.json").read_text())
        result,_=interpret(meta,(dest/"stdout").read_text())
        save(dest/"result.json",result)
        if meta["timed_out"] or meta["exit_code"]!=10 or result["adapter_query_count"]!=1:
            raise RuntimeError(f"unexpected native outcome: {dest}")


if __name__=="__main__": main()
