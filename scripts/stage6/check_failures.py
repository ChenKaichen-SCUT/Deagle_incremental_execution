#!/usr/bin/env python3
"""Exercise single-update failure gates and comparator classifications without paid requests."""
import argparse
import difflib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.comparison import compare
from incdeagle.model.identity import read, save
from incdeagle.repair import PROTECTED


def require(value, reason):
    if not value:
        raise ValueError(reason)


def diff(old,new,filename="program.c"):
    return "".join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),
                                       fromfile="a/"+filename,tofile="b/"+filename))


def check(out, complete_run):
    out.mkdir(parents=True,exist_ok=False)
    source=ROOT/"cases/batch_total"
    original=(source/"old/program.c").read_text()
    outputs={}
    def trial(label, manifest, args, expected, *, empty_key=False):
        dest=out/label
        command=[sys.executable,"-B","-m","incdeagle.cli","run-case","--case",str(manifest),"--out",str(dest),*args]
        proc=subprocess.run(command,cwd=ROOT,input=b"" if empty_key else None,capture_output=True)
        record=read(dest/"workflow.json")
        require(record["status"]==expected and proc.returncode==(0 if expected=="OLD_NOT_VIOLATION" else 2),
                label+" produced "+str(record))
        require(not record["baseline_started"] and not (dest/"frozen.json").exists() and not (dest/"baseline").exists(),
                label+" reached full verification")
        outputs[label]={"status":record["status"],"reason":record.get("online_reason"),"baseline_started":False,
                        "cli_exit":proc.returncode,"repair_usage":record["repair_usage"]}
        return dest
    bad=out/"syntax.diff"
    bad.write_text(diff(original,original.replace("boxes * 2;","boxes * ;")))
    trial("malformed_source",source/"task.yaml",["--repair","manual","--patch",str(bad)],"INVALID_PATCH")
    bad=out/"protected.diff"
    harness=(source/"harness.c").read_text()
    bad.write_text(diff(harness,harness.replace("== 6","== 4"),"harness.c"))
    trial("protected_edit",source/"task.yaml",["--repair","manual","--patch",str(bad)],"INVALID_PATCH")
    fail=trial("missing_credential",source/"task.yaml",["--repair","mini","--key-stdin"],"REPAIR_FAILED",empty_key=True)
    missing=read(fail/"repair/model.json")
    require(missing["requests"]==[] and missing.get("error_reason")=="empty_controller_credential",
            "Missing credential did not stop before the provider")
    wrong=trial("wrong_input_digest",source/"task.yaml",
                ["--repair","mini","--key-stdin","--repair-input-sha256","0"*64],"REPAIR_FAILED",empty_key=True)
    mismatched=read(wrong/"repair/model.json")
    require(mismatched["requests"]==[] and mismatched.get("error_reason")=="approved_input_digest_mismatch",
            "Different model input reached credential handling")
    # A standalone old-program eligibility check. No candidate is present or requested from a model.
    eligible=out/"eligibility_input"/source.name
    for file in PROTECTED:
        dst=eligible/file
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/("candidate/program.c" if file=="old/program.c" else file),dst)
    skipped=trial("old_not_violation",eligible/"task.yaml",["--repair","manual"],"OLD_NOT_VIOLATION")
    require(not (skipped/"repair/input.json").exists() and not (skipped/"snapshot"/source.name/"candidate").exists(),
            "A candidate was created after a nonviolating P0")
    # Use a real passing result as one input. The following alternate records are comparator fixtures.
    passing=read(complete_run/"baseline/verification.json")["result"]
    require(passing["classification"]=="NO_VIOLATION_WITHIN_BOUND","Expected a genuine passing comparison fixture")
    conflict=dict(passing,classification="VIOLATION",properties={passing["target"]:"FAILURE"})
    require(compare(passing,conflict)=="DEFINITE_CONFLICT","Missed contradictory determinate outcomes")
    statuses={s:compare(passing,dict(passing,classification=s)) for s in
              ("UNKNOWN","TIMEOUT","OOM","ERROR","INCOMPLETE_UNWINDING")}
    require(set(statuses.values())=={"INCONCLUSIVE"},"Resource failure was treated as a logical contradiction")
    save(out/"probes.json",{"actual_runs":outputs,"comparator_fixtures":{"contradictory":"DEFINITE_CONFLICT",**statuses}})
    print("Five actual failure/eligibility runs and six comparator fixture classifications passed.")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--passing-run",type=Path,required=True)
    a=p.parse_args()
    check(a.out.resolve(),a.passing_run.resolve())
