"""Compare a frozen P1 in an independent full verifier and a freshly warmed native session."""
import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.comparison import compare
from incdeagle.model.identity import read, save
from incdeagle.repair import apply_source_patch
from incdeagle.workflow import doctor, execute
from scripts.stage7.inputs import LARGE, SMALL, prepare, validate

STEP=.005


def sample(group):
    """Sum RSS across service processes; shared pages may appear in multiple processes."""
    try:
        pids=(group/"cgroup.procs").read_text().split()
        charged=int((group/"memory.current").read_text())
    except (FileNotFoundError,ProcessLookupError):
        return None
    rss=0
    for pid in pids:
        try:
            rss+=int((Path("/proc")/pid/"statm").read_text().split()[1])*os.sysconf("SC_PAGE_SIZE")//1024
        except (FileNotFoundError,ProcessLookupError,IndexError):
            pass
    return [time.monotonic_ns(),rss,charged//1024,len(pids)]


def measure(case,folder,phase):
    if folder.exists():
        raise ValueError("Measurement directory already exists: "+str(folder))
    folder.mkdir(parents=True)
    gamma=read(case/"gamma.json")
    lim=gamma["limits"]
    unit="incdeagle7-"+uuid.uuid4().hex
    budget=lim["timeout_seconds"]*(2 if phase=="incremental" else 1)+20
    command=["systemd-run","--quiet","--pipe","--wait","--collect","--unit",unit,
             "-p","WorkingDirectory="+str(ROOT),"-p","MemoryMax="+str(lim["memory_bytes"]),"--setenv=LC_ALL=C",
             "--","/usr/bin/timeout","--kill-after=5",str(budget),sys.executable,"-B",
             str(ROOT/"scripts/stage7/worker.py"),str(case),str(folder),phase]
    samples=[]
    group=None
    with (folder/"service.stdout").open("wb") as out,(folder/"service.stderr").open("wb") as err:
        launch=time.monotonic_ns()
        proc=subprocess.Popen(command,stdout=out,stderr=err,stdin=subprocess.DEVNULL)
        while proc.poll() is None:
            if group is None:
                try:
                    group=Path(read(folder/"group.json")["path"])
                    if group.name!=unit+".service":raise ValueError("Resource probe attached to wrong group")
                except (FileNotFoundError,json.JSONDecodeError):
                    pass
            if group is not None:
                point=sample(group)
                if point:samples.append(point)
            time.sleep(STEP)
        stop=time.monotonic_ns()
    path=folder/"measurement.json"
    if not path.is_file():
        log=subprocess.run(["journalctl","--no-pager","-o","cat","-u",unit+".service"],capture_output=True).stdout.lower()
        status="OOM" if any(x in log for x in (b"oom-kill",b"out of memory",b"oom killer")) else ("TIMEOUT" if proc.returncode==124 else "ERROR")
        save(path,{"status":status,"phase":phase,"times":{},"reason":"Worker exited before returning a result",
                   "max_waited_child_rss_kib":None})
    record=read(path)
    if proc.returncode and record["status"]=="COMPLETED":raise ValueError("Successful result from a failed service")
    save(folder/"service.json",{"argv":command,"returncode":proc.returncode,"launch_ns":launch,"finish_ns":stop,
         "memory_max":lim["memory_bytes"],"timeout_seconds":lim["timeout_seconds"],"unit":unit,
         "sample_columns":["monotonic_ns","sum_rss_kib","cgroup_current_kib","processes"],"target_sampling_interval_s":STEP,
         "samples":samples})
    return record


def diagnostics(out,name,case):
    dest=out/"diagnostics"/name
    if not (dest/"workflow.json").exists():
        execute(case/"task.yaml",method="replay",out=dest,check_model=True)
    workflow=read(dest/"workflow.json")
    if workflow.get("agreement") in ("DEFINITE_CONFLICT","PROPERTY_DETAILS_DIFFER") or workflow["status"]=="MODEL_MISMATCH":
        raise RuntimeError("Correctness conflict at "+str(dest))
    if (workflow.get("candidate_sha256") is not None and
            workflow["candidate_sha256"]!=read(case/"freeze.json")["files_sha256"]["candidate/program.c"]):
        raise ValueError("Diagnostic was run on different candidate bytes")
    return workflow


def run(out, names, repetitions, diagnostics_only):
    out.mkdir(parents=True,exist_ok=True)
    setup=doctor()
    if not setup["native_ready"]:raise ValueError("Locked tools unavailable")
    save(out/"doctor.json",setup)
    for group,available in (("existing",SMALL),("expanded",LARGE)):
        if any(n in available for n in names):prepare(out,group)
    matrix=read(out/"matrix.json")
    for name in names:
        case=validate(out,matrix[name])
        w=diagnostics(out,name,case)
        print("diagnostic",name,w["status"],flush=True)
    if diagnostics_only:return
    schedule=[]
    for r in range(repetitions):
        rotated=names[r%len(names):]+names[:r%len(names)]
        for name in rotated:
            idx=names.index(name)
            order=(["old_full","full","incremental"] if (r+idx)%2==0 else ["incremental","old_full","full"])
            schedule.append({"case_id":name,"repeat":r+1,"order":order})
    plan={"repetitions":repetitions,"cases":names,"schedule":schedule,"diagnostics_in_formal_runs":False,
          "file_cache":"Existing/warm OS caches after separate diagnostic runs. No global cache manipulation.",
          "single_active_verification":True}
    prior_plan=out/"plan.json"
    if prior_plan.is_file() and read(prior_plan)!=plan:
        raise ValueError("Existing experiment has a different schedule; select a new output directory")
    save(prior_plan,plan)
    for item in schedule:
        name=item["case_id"]
        trial=out/"trials"/name/str(item["repeat"])
        if (trial/"trial.json").is_file():
            old=read(trial/"trial.json")
            if old["agreement"] in ("DEFINITE_CONFLICT","PROPERTY_DETAILS_DIFFER"):
                raise RuntimeError("Previously recorded conflict")
            continue
        trial.mkdir(parents=True,exist_ok=False)
        case=validate(out,matrix[name])
        # The same measured repair cost is used in both replay-cycle totals.
        before=time.monotonic_ns()
        candidate=apply_source_patch((case/"old/program.c").read_bytes(),(case/"patch.diff").read_bytes())
        if candidate!=(case/"candidate/program.c").read_bytes():raise ValueError("Invalid frozen diff")
        repair=(time.monotonic_ns()-before)/1e9
        records={}
        for phase in item["order"]:
            records[phase]=measure(case,trial/phase,phase)
        def verdict(phase):
            row=records[phase]
            return row.get("verdict",{"classification":row["status"]})
        agreement=compare(verdict("incremental"),verdict("full"))
        old=verdict("old_full")
        data={**item,"agreement":agreement,"statuses":{p:r["status"] for p,r in records.items()},
              "old_full_verdict":old,"old_instrumented_verdict":records["incremental"].get("old_verdict"),
              "verified_replay_patch_seconds":repair,"api_calls":0}
        save(trial/"trial.json",data)
        print("trial",name,item["repeat"],agreement,data["statuses"],flush=True)
        if agreement in ("DEFINITE_CONFLICT","PROPERTY_DETAILS_DIFFER") or (
                data["old_instrumented_verdict"] is not None and old.get("classification")=="VIOLATION"
                and old!=data["old_instrumented_verdict"]):
            raise RuntimeError("Determinate conflict at "+str(trial))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--repetitions",type=int,default=3)
    p.add_argument("--only",nargs="+",choices=[*SMALL,*LARGE])
    p.add_argument("--diagnostics-only",action="store_true")
    a=p.parse_args()
    if a.repetitions<1:p.error("At least one matched repetition is required")
    key=ROOT/"runs/stage-07/experiment.lock"
    key.parent.mkdir(exist_ok=True,parents=True)
    with key.open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        run(a.out.resolve(),a.only or [*SMALL,*LARGE],a.repetitions,a.diagnostics_only)
