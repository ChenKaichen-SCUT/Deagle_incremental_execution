"""Frozen D3 matrix. Pin CPU, interleave modes and preserve every new process."""
import argparse
import gzip
import json
from pathlib import Path

from package_d1 import metrics, trace_comparison
from run_d1 import CASES
from run_stock import BASE, run, save, sha
from summarize_stock import interpret


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("new_dir", type=Path)
    parser.add_argument("--pilot", action="store_true")
    a = parser.parse_args()
    exe, dest = a.binary.resolve(), a.new_dir.resolve()
    dest.mkdir(parents=True, exist_ok=False)
    lock = BASE / "bench/manifest.json"
    specs = json.loads(lock.read_text())
    modes = ("off", "boolean", "mixed")
    plan = []
    for rep in range(1 if a.pilot else 3):
        for case_index, case in enumerate(CASES):
            order = ("joint",) if a.pilot else tuple(modes[(i+case_index+rep)%3] for i in range(3))
            for mode in order:
                plan.append([case,rep+1,mode])
    if not a.pilot:
        plan.extend([case,1,"joint"] for case in CASES)
    binary_hash = sha(exe)
    save(dest / "plan.json", dict(schedule=plan, executable_sha256=binary_hash,
         input_lock_sha256=sha(lock), cpu=0, fresh_process=True, os_cache="unmanaged"))
    for case, rep, mode in plan:
        folder = dest / case / f"{mode}-{rep}"
        flags = []
        if mode == "joint":
            flags += ["--d1-manifest", str(folder/"native.tsv"), "--d3-layouts"]
        if mode != "off":
            flags += ["--d2-proof" if mode == "boolean" else "--d3-proof", str(folder/"proof.bin")]
        spec = dict(specs[case])
        spec["argv"] = [*flags,*spec["argv"]]
        run(exe,spec,case,"P0",folder,binary_hash)
        meta = json.loads((folder/"run.json").read_text())
        actual, trace = interpret(meta, (folder/"stdout").read_text())
        save(folder/"result.json",actual)
        with gzip.open(BASE/"reports/evidence/d1/runs/off"/case/"P0/result.json.gz","rt") as f:
            ref,witness = json.load(f)
        comparison = trace_comparison(witness,trace)
        save(folder/"trace.json",comparison)
        if metrics(actual)!=metrics(ref) or meta["timed_out"] or meta["exit_code"]!=10:
            raise ValueError(f"native result changed in {folder}")


if __name__=="__main__": main()
