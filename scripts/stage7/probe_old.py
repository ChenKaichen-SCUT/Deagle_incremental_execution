"""Diagnose the six-agent old-solver time using frozen P0 and freshly built executables."""
import argparse
import shutil
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.adapters.deagle import classify
from incdeagle.comparison import bounded
from incdeagle.model.identity import file_sha, read, save
from scripts.stage2.check_case import load_case
from scripts.stage7.results import runtime_messages


def run(experiment,build_root,out):
    item=read(experiment/"matrix.json")["airline_reservations_6"]
    case=experiment/item["case_dir"]
    _,gamma,phi=load_case(case)
    lock=read(ROOT/"configs/stage05.lock.json")
    out.mkdir(parents=True,exist_ok=False)
    records={}
    for label,tree,expected,observe in (("baseline","deagle-baseline",lock["baseline_sha256"],False),
           ("enhanced_plain","deagle-stage5",lock["development_sha256"],False),
           ("enhanced_observed","deagle-stage5",lock["development_sha256"],True)):
        d=out/label
        d.mkdir()
        binary=build_root/"third_party"/tree/"src/cbmc/deagle_exe"
        if file_sha(binary)!=expected:raise ValueError("Rebuilt executable differs from lock")
        for src,name in ((case/"old/program.c","program.c"),(case/"harness.c","harness.c")):
            shutil.copyfile(src,d/name)
        opts=[binary,*gamma["source_argv"],*gamma["verification_output"],"harness.c"]
        env={"INCDEAGLE_JSON_OUTPUT":d/"result.json"}
        if observe:env["INCDEAGLE_OBSERVE_DIR"]=d
        receipt=bounded(opts,d,d,gamma["limits"],env=env)
        result,row=classify((d/"result.json").read_bytes(),receipt["exit_code"],phi)
        if result["classification"]!="VIOLATION":raise ValueError("Lost original assertion failure")
        records[label]={"result":result,"steps":len(row["trace"]),"runtime":runtime_messages(d/"result.json"),
                        "binary_sha256":expected,"source_sha256":file_sha(d/"program.c"),
                        "wall_seconds":receipt["wall_ns"]/1e9,"old_cache_collection":False,"observer":observe}
    save(out/"comparison.json",records)
    for k,r in records.items():print(k,r["wall_seconds"],r["runtime"].get("Solver"),r["steps"])


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--experiment",required=True,type=Path)
    p.add_argument("--build-root",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    run(a.experiment.resolve(),a.build_root.resolve(),a.out.resolve())
