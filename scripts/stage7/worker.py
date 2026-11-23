"""Measure one complete verifier path inside a private, memory-limited Linux service."""
import json
import os
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.adapters.deagle import classify
from incdeagle.counterexample import normalize
from incdeagle.model.identity import file_sha, read, save
from incdeagle.repair import CandidateProvider, Outcome, original_hashes
from incdeagle.workflow import oom_count, snapshot
from scripts.stage2.check_case import BINARY, load_case
from scripts.stage4 import session as native
from scripts.stage5.session import TheorySession, summarize_theory


def group():
    entry=next(s[3:] for s in Path("/proc/self/cgroup").read_text().splitlines() if s.startswith("0::"))
    return Path("/sys/fs/cgroup")/entry.lstrip("/")


def mark():
    cpu=dict(s.split() for s in (group()/"cpu.stat").read_text().splitlines())
    return {"monotonic_ns":time.monotonic_ns(),"cpu_usage_us":int(cpu["usage_usec"]),
            "user_us":int(cpu["user_usec"]),"system_us":int(cpu["system_usec"])}


def normalized(folder, target, phi, gamma, files, version):
    if target is None:
        return None
    trace=normalize(target,phi,gamma,files,"result.json",version=version)
    path=folder/("cex0.json" if version=="old" else "cex1.json")
    save(path,trace)
    return {"sha256":file_sha(path),"steps":trace["step_count"],"failure":trace["failure"]["source"],
            "source_hash":files["program.c"],"property":trace["property"]}


def plain(case, folder, phase, times):
    task,gamma,phi=load_case(case)
    dest=folder/"verify"
    dest.mkdir()
    times[phase+"_start"]=mark()
    file=case/task["old_source" if phase=="old_full" else "candidate_source"]
    for source,name in ((file,"program.c"),(case/"harness.c","harness.c")):
        shutil.copyfile(source,dest/name)
        if file_sha(dest/name)!=file_sha(source):
            raise ValueError("Full path received different source bytes")
    if file_sha(BINARY)!=gamma["binary_sha256"]:
        raise ValueError("Wrong independent baseline")
    opts=[str(BINARY),*gamma["source_argv"],*gamma["verification_output"],"harness.c"]
    cmd=["/usr/bin/timeout","--kill-after=5",str(gamma["limits"]["timeout_seconds"]),*opts]
    env={k:v for k,v in os.environ.items() if not k.startswith("INCDEAGLE_")}
    env.update(LC_ALL="C",INCDEAGLE_JSON_OUTPUT=str(dest/"result.json"))
    with (dest/"diagnostic.stdout").open("wb") as out,(dest/"diagnostic.stderr").open("wb") as err:
        rc=subprocess.run(cmd,cwd=dest,env=env,stdout=out,stderr=err,stdin=subprocess.DEVNULL).returncode
    if rc==124:raise TimeoutError("Independent Deagle reached the case timeout")
    raw=(dest/"result.json").read_bytes()
    result,row=classify(raw,rc,phi)
    if rc in (0,10):
        console=(dest/"diagnostic.stdout").read_bytes()
        if not all(x in console for x in (b"Use Deagle's closure solver",b"Set Deagle closure solver's graph")):
            raise ValueError("Full run lacks native backend evidence")
    files={"program.c":file_sha(file),"harness.c":file_sha(case/"harness.c")}
    version="old" if phase=="old_full" else "candidate"
    trace=normalized(dest,row if result["classification"]=="VIOLATION" else None,phi,gamma,files,version)
    save(dest/"verdict.json",result)
    times[phase+"_end"]=mark()
    return {"verdict":result,"trace":trace,"command":cmd,"exit_code":rc,"inputs":files,"binary_sha256":gamma["binary_sha256"]}


class FrozenReplay(CandidateProvider):
    """Keep the native session alive; charge admission and all P1 maintenance to the update."""
    def __init__(self, run, staged, source, files, times):
        super().__init__(run,staged,{"case_dir":str(source),"protected_sha256":{k:files[k] for k in original_hashes(staged)}})
        self.files=files
        self.times=times
        self.cex=None

    def produce(self, old, verdict, target, ready, process, warmup_wall):
        self.intact()
        files={"program.c":file_sha(old/"program.c"),"harness.c":file_sha(old/"harness.c")}
        if files["program.c"]!=self.files["old/program.c"] or files["harness.c"]!=self.files["harness.c"]:
            raise ValueError("Wrong native P0")
        self.cex=normalized(old,target,self.phi,self.gamma,files,"old")
        if ready and (process.pid!=ready["checkpoint_pid"] or process.poll() is not None):
            raise ValueError("Lost live checkpoint before submitting P1")
        save(self.repair/"old-binding.json",{"verdict":verdict,"trace":self.cex,"checkpoint":ready,
             "cache_sha256":file_sha(old/"lemma-cache.json"),"source_sha256":files["program.c"]})
        boundary=mark()
        self.times.update(old_instrumented_end=boundary,incremental_start=boundary)
        dst=self.case/"candidate/program.c"
        dst.parent.mkdir()
        shutil.copyfile(self.source_case/"candidate/program.c",dst)
        dst.chmod(0o444)
        if file_sha(dst)!=self.files["candidate/program.c"]:
            raise ValueError("Different frozen P1")
        self.seal={"case":self.case.name,"candidate_sha256":file_sha(dst),"protected_sha256":self.initial,
                   "old_version":read(old/"manifest.json")["version_sha256"],"patch_sha256":self.files["patch.diff"]}


def incremental(case, folder, times):
    times["old_instrumented_start"]=mark()
    _,staged=snapshot(case,folder)
    files=read(case/"freeze.json")["files_sha256"]
    provider=FrozenReplay(folder,staged,case,files,times)
    real_context=native.candidate_context
    change_times=[]
    def measured_context(*args):
        before=time.monotonic_ns()
        try:
            return real_context(*args)
        finally:
            change_times.append((time.monotonic_ns()-before)/1e9)
    # The worker owns a single process and runs exactly one session.
    with patch.object(native,"candidate_context",measured_context):
        session=native.run_pair(staged,folder/"pair",theory=TheorySession(),candidate_provider=provider)
    if session["candidate"] is None:
        raise Outcome("OLD_NOT_VIOLATION","P0 ineligible for repair")
    provider.intact()
    dest=folder/"pair/candidate"
    result,row=classify((dest/"result.json").read_bytes(),session["candidate_exit"],provider.phi)
    if result!=session["candidate"]:raise ValueError("P1 result differs from native session")
    trace=normalized(dest,row if result["classification"]=="VIOLATION" else None,provider.phi,provider.gamma,
                     session["inputs_sha256"],"candidate")
    theory=summarize_theory(folder/"pair")
    if session["inputs_sha256"]!={"program.c":files["candidate/program.c"],"harness.c":files["harness.c"]}:
        raise ValueError("Online verifier results belong to different bytes")
    save(dest/"verdict.json",result)
    times["incremental_end"]=mark()
    return {"verdict":result,"old_verdict":session["old"],"trace":trace,"old_trace":provider.cex,"path":session["path"],
            "fallback_reason":session["fallback_reason"],"inputs":session["inputs_sha256"],"old_version":session["old_version"],
            "new_version":session["candidate_version"],"frontend_seconds":session["candidate_frontend_wall_seconds"],
            "change_analysis_seconds":sum(change_times),"native":session["native"],"theory":theory}


def main():
    case,folder=map(Path,sys.argv[1:3])
    phase=sys.argv[3]
    times={}
    save(folder/"group.json",{"path":str(group()),"pid":os.getpid()})
    pre=oom_count()
    try:
        _,gamma,_=load_case(case)
        if int((group()/"memory.max").read_text())!=gamma["limits"]["memory_bytes"]:
            raise ValueError("Unexpected memory budget")
        result=incremental(case,folder,times) if phase=="incremental" else plain(case,folder,phase,times)
        data={"status":"COMPLETED",**result}
    except Exception as exc:
        code=exc.status if isinstance(exc,Outcome) else "ERROR"
        if isinstance(exc,(TimeoutError,subprocess.TimeoutExpired)):code="TIMEOUT"
        after=oom_count()
        if pre is not None and after is not None and after>pre:code="OOM"
        data={"status":code,"reason":str(exc),"exception":type(exc).__name__}
    data.update(phase=phase,times=times,worker_end=mark(),max_waited_child_rss_kib=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
                controller_hwm_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    save(folder/"measurement.json",data)


if __name__=="__main__":
    main()
