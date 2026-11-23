#!/usr/bin/env python3
"""Independent oracle checks after one incremental session has finished."""
import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.adapters.deagle import classify
from incdeagle.model.identity import read, save, file_sha
from incdeagle.model.compare import delta
from incdeagle.model.observe import build_model
from incdeagle.model.repeat import phase_digest
from scripts.stage2.check_case import check, load_case
from scripts.stage4.session import BINARY, CASES


def require(value, why):
    if not value:raise ValueError(why)


def verify(name,out,*,batch_error_probe=False):
    case=CASES[name]
    out.mkdir(parents=True,exist_ok=False)
    if batch_error_probe:
        require(name == "batch_total", "Retained-error probe uses the batch_total harness")
        case = out / "inputs" / name
        case.mkdir(parents=True)
        for file in ("task.yaml", "harness.c", "phi.json", "gamma.json"):
            shutil.copyfile(CASES[name] / file, case / file)
        for version in ("old", "candidate"):
            (case / version).mkdir()
        old_program = (CASES[name] / "old/program.c").read_bytes()
        require(old_program.count(b"boxes * 2") == 1, "Unexpected old batch_total source")
        (case / "old/program.c").write_bytes(old_program)
        (case / "candidate/program.c").write_bytes(old_program.replace(b"boxes * 2", b"boxes * 5"))
    _,gamma,phi=load_case(case)
    pair=out/"pair"
    cmd=[sys.executable,"-B",str(ROOT/"scripts/stage4/session.py"),name,"--out",str(pair)]
    if batch_error_probe:
        cmd.extend(["--case-dir", str(case)])
    subprocess.run(cmd,check=True)
    s=read(pair/"session.json")
    sync_cases = {"split_counter": "record_one", "partial_counter": "record_left"}
    if name in sync_cases:
        require(s["path"] == "full_fallback" and
                s["fallback_reason"] == "synchronization_calls_changed:" + sync_cases[name],
                "Expected conservative synchronization fallback")
    else:
        require(s["path"] == "incremental" and not s["fallback_reason"],
                "Expected native incremental execution")
    expected_result = "VIOLATION" if batch_error_probe or name == "partial_counter" else "NO_VIOLATION_WITHIN_BOUND"
    require(s["candidate"]["classification"] == expected_result and s["old"]["classification"] == "VIOLATION",
            "Case verdict differs from the frozen expectation")
    # The independent full models are first launched after the online pair has ended.
    full=out/"full"
    full.mkdir()
    for f in ("harness.c","program.c"):shutil.copyfile(pair/"candidate"/f,full/f)
    argv=[str(BINARY),*gamma["source_argv"],*gamma["verification_output"],"harness.c"]
    env=["--setenv=INCDEAGLE_OBSERVE_DIR="+str(full),"--setenv=INCDEAGLE_JSON_OUTPUT="+str(full/"result.json")]
    start=time.monotonic()
    with (full/"diagnostic.stdout").open("wb") as stdout,(full/"diagnostic.stderr").open("wb") as stderr:
        rc=subprocess.run(["systemd-run","--quiet","--wait","--pipe","--collect","-p","WorkingDirectory="+str(full),
                   "-p","MemoryMax="+str(gamma["limits"]["memory_bytes"]),"--setenv=LC_ALL=C",*env,"--",
                   "/usr/bin/timeout","--kill-after=5",str(gamma["limits"]["timeout_seconds"]),*argv],
                   stdout=stdout,stderr=stderr).returncode
    full_wall=time.monotonic()-start
    ref,_=classify((full/"result.json").read_bytes(),rc,phi)
    trusted={role:check(case,role,out/"independent"/role) for role in ("old","candidate")}
    for role,v in trusted.items():
        require(all(v[k]==s[role][k] for k in s[role]),"Independent baseline mismatch on "+role)
    require(ref==s["candidate"] and rc==s["candidate_exit"],"Full development result differs")
    d=pair/"candidate"
    for f in ("harness.c","program.c"):require(file_sha(d/f)==file_sha(full/f)==trusted["candidate"]["input_sha256"][f],"Different input bytes")
    phases={}
    for f in ("goto","raw_ssa","sc_input","full_model"):
        phases[f]={role:phase_digest(read(directory/(f+".json"))) for role,directory in (("online",d),("full",full))}
    # Validate both the canonical event/constraint mapping and exact native SSA rows,
    # guards, types, per-read coverage and graph endpoints in the instrumented build.
    models={role:build_model(directory,phi["id"]) for role,directory in (("online",d),("full",full))}
    old_model=build_model(pair/"old",phi["id"])
    diff=delta(old_model,models["online"],read(pair/"old/manifest.json"),read(pair/"frontend/manifest.json"))
    diff["analysis_changes"]["scope"] = (
        "Post-run differences of bounded observed models. Native restoration separately checks the "
        "whole-program dirty set, per-function safe-pointer summaries, and the typed program image."
    )
    diff.update(schema=4,checkpoint_used=s["native"]["checkpoint_used"],fallback_reason=s["fallback_reason"],
                native_construction=s["native"]["sc_counters"],purpose="post-run structural comparison")
    save(out/"model-delta.json",diff)
    differences=[k for k,x in phases.items() if x["online"]!=x["full"]]
    digests={role:m["structure_sha256"] for role,m in models.items()}
    semantic={role:{"event_fingerprints":len(m["events"]),"constraint_fragments":len(m["fragments"]),
                    "counts":m["counts"]} for role,m in models.items()}
    n=s["native"]; full_trace=read(full/"visits.json")
    if s["path"]=="incremental":
        native=read(d/"native-stats.json")
        prefix=native["reused_prefix_symex_steps"]
        trace=[{k:r[k] for k in ("function","pc","thread")} for r in full_trace]
        old=read(pair/"old/native-stats.json")["executed_dispatches"]
        prefix_ok=old[:prefix]==trace[:prefix]
        suffix_ok=native["executed_dispatches"]==trace[prefix:]
        require(prefix>0 and prefix_ok and suffix_ok and len(trace)==prefix+n["executed_symex_steps"],"Dispatch accounting failed")
        require(n["sc_counters"].get("read_bundles_reused",0)>0 and n["sc_counters"].get("coverage_formulas_reused",0)>0,
                "No native read bundle entered the candidate solver")
    else:
        prefix_ok=suffix_ok=None
        require(n["executed_symex_steps"]==len(full_trace),"Fallback was not a full rebuild")
    result={"case":name,"old":s["old"]["classification"],"candidate":ref["classification"],"path":s["path"],
            "fallback_reason":s["fallback_reason"],"baseline_matches":True,"phase_digests":phases,"model_digests":digests,
            "different_phases":differences,"counts":semantic,"full_dispatches":len(full_trace),
            "prefix_dispatch_trace_matches":prefix_ok,"suffix_dispatch_trace_matches":suffix_ok,"native":n,
            "candidate_trace_steps":s["candidate_trace_steps"],"full_wall_seconds":full_wall,
            "online_candidate_seconds":s["candidate_wall_seconds"],"old_warmup_seconds":s["old_warmup_wall_seconds"],
            "frontend_seconds":s["candidate_frontend_wall_seconds"],"full_candidate_exit":rc,
            "full_oracle_started_after_online":True}
    save(out/"acceptance.json",result)
    require(not differences and digests["online"]==digests["full"],"Model comparison differs: "+str(differences))
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("case",choices=sorted(CASES));p.add_argument("--out",type=Path,required=True)
    p.add_argument("--batch-error-probe", action="store_true",
                   help="run a still-incorrect multiplier candidate on a private copy of the batch_total harness")
    a=p.parse_args()
    r=verify(a.case,a.out.resolve(),batch_error_probe=a.batch_error_probe)
    print(r["case"],r["path"],r["fallback_reason"],r["full_dispatches"],r["native"]["executed_symex_steps"])
