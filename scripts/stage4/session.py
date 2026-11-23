#!/usr/bin/env python3
"""One Linux P0 → P1 verification, in a bounded cgroup, with an immutable fork checkpoint."""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import yaml
from contextlib import ExitStack
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.stage3.session import CASES, memory_max
from scripts.stage2.check_case import load_case
from scripts.stage4.change_provider import changes
from incdeagle.adapters.deagle import classify
from incdeagle.model.compare import manifest
from incdeagle.model.identity import file_sha, read, save

BINARY = ROOT / "third_party/deagle-stage4/src/cbmc/deagle_exe"


def clean_process(proc):
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
    if proc.stdin:
        proc.stdin.close()


def candidate_context(old, front, case, gamma, phi, lock, gcc, frontend_exit):
    """Return provenance and the reason a frontend can or cannot support restoration."""
    if frontend_exit:
        return [], {"preflight_refusal": f"candidate_frontend_failed_exit_{frontend_exit}"}
    if not (front / "goto.irep").is_file():
        return [], {"preflight_refusal": "candidate_goto_image_missing"}
    versions = []
    try:
        for folder in (old, front):
            version = manifest(folder, case, gamma, phi, lock, gcc)
            save(folder / "manifest.json", version)
            versions.append(version)
        diff = changes(old, front, versions)
    except (OSError, KeyError, TypeError, ValueError, IndexError) as error:
        diff = {"preflight_refusal": "frontend_dependency_check_failed", "detail": str(error)}
    return versions, diff


def run_pair(case, out, *, checkpoint_bytes=None, theory=None):
    task, gamma, phi = load_case(case)
    if int(memory_max()) != gamma["limits"]["memory_bytes"]:
        raise RuntimeError("Wrong cgroup limit")
    timeout = gamma["limits"]["timeout_seconds"]
    out.mkdir(parents=True, exist_ok=False)
    old, front, cand, working, tools = (out / role for role in ("old","frontend","candidate","source","tools"))
    for d in (old,front,cand,working,tools):
        d.mkdir()
        if d != tools:
            shutil.copyfile(case / "harness.c", d / "harness.c")
    shutil.copyfile(ROOT / "scripts/stage3/record_gcc.py", tools / "gcc")
    (tools / "gcc").chmod(0o755)
    for d, version in ((old, "old_source"), (front,"candidate_source"), (cand,"candidate_source")):
        shutil.copyfile(case / task[version], d / "program.c")
    shutil.copyfile(old / "program.c", working / "program.c")
    binary = theory.binary if theory else BINARY
    cmd = [str(binary), *gamma["source_argv"], *gamma["verification_output"], "harness.c"]
    base_env = dict(os.environ, PATH=str(tools) + ":" + os.environ["PATH"], LC_ALL="C")
    for k in tuple(base_env):
        if k.startswith("INCDEAGLE_"):
            del base_env[k]
    build_id = str(subprocess.check_output(["git","-C",str(binary.parents[2]),"rev-parse","HEAD"],text=True)).strip()
    lock = {"development_sha256":file_sha(binary), "commit":build_id, "schema":1}
    expected = read(theory.release_lock if theory else ROOT / "configs/stage04.lock.json")
    if build_id != expected["development_commit"] or lock["development_sha256"] != expected["development_sha256"]:
        raise ValueError("Executable or source commit differs from the release lock")
    if theory:
        base_env.update(theory.prepare(out, lock))
    gcc_path = Path("/usr/bin/gcc").resolve()
    gcc = {"binary":str(gcc_path),"sha256":file_sha(gcc_path),
           "version":subprocess.check_output([gcc_path,"-dumpfullversion"],text=True).strip()}
    update_start = None
    with ExitStack() as stack:
        def start(d, **extra):
            env = dict(base_env, INCDEAGLE_OBSERVE_DIR=str(d), INCDEAGLE_JSON_OUTPUT=str(d/"result.json"),
                       INCDEAGLE_CPP_RECORD=str(d/"cpp.jsonl"), **extra)
            proc = subprocess.Popen(cmd,cwd=working,env=env,stdin=subprocess.PIPE,start_new_session=True,
                                    stdout=stack.enter_context((d/"diagnostic.stdout").open("wb")),
                                    stderr=stack.enter_context((d/"diagnostic.stderr").open("wb")))
            stack.callback(clean_process,proc)
            return proc

        begin = time.monotonic()
        budget=yaml.safe_load((ROOT/"configs/project.yaml").read_bytes())["resources"]["checkpoints"]
        limit_bytes=budget["max_total_bytes"] if budget["max_count"]>=1 else 0
        if checkpoint_bytes is not None:
            if checkpoint_bytes<0:raise ValueError("Checkpoint budget must be nonnegative")
            limit_bytes=min(limit_bytes,checkpoint_bytes)
        original = start(old, INCDEAGLE_S4_ROOT=str(out),INCDEAGLE_S4_BUDGET_BYTES=str(limit_bytes))
        while not (out/"old_done.json").exists() and original.poll() is None:
            if time.monotonic()-begin >= timeout:
                raise TimeoutError("Old build/verification exceeded case budget")
            time.sleep(.005)
        ready = read(out/"old_done.json") if (out/"old_done.json").exists() else {}
        old_exit = ready.get("old_exit", original.poll())
        old_result, old_target = classify((old/"result.json").read_bytes(),old_exit,phi)
        if old_result["classification"] != "VIOLATION":
            raise ValueError("Expected P0 target failure")
        if theory:
            old_manifest = manifest(old, case, gamma, phi, lock, gcc)
            save(old / "manifest.json", old_manifest)
            theory.capture(old, old_manifest)
        warmup_wall = time.monotonic()-begin
        update_start = time.monotonic()
        def remaining():
            left = timeout - (time.monotonic()-update_start)
            if left <= 0: raise TimeoutError("Candidate frontend, maintenance and verification exceeded case budget")
            return left
        shutil.copyfile(cand/"program.c",working/"program.c")
        before_front = time.monotonic()
        compiler = start(front,INCDEAGLE_S4_ROOT=str(out),INCDEAGLE_S4_FRONTEND="1")
        frontend_exit = compiler.wait(timeout=remaining())
        frontend_wall=time.monotonic()-before_front
        versions, diff = candidate_context(old, front, case, gamma, phi, lock, gcc, frontend_exit)
        save(out/"source-changes.json",diff)
        reason=diff["preflight_refusal"]
        old_stats = read(old / "native-stats.json")
        if ready:
            cache=old/"fragments.irep"
            cache_budget = limit_bytes - old_stats["checkpoint_virtual_bytes_upper_bound"]
            if not cache.is_file() or not 0 < cache.stat().st_size <= cache_budget:
                reason=reason or "missing_or_oversize_read_bundle_cache"
            original.stdin.write((("FULL "+reason if reason else "APPLY")+"\n").encode())
            original.stdin.flush()
            rc=original.wait(timeout=remaining())
            if rc==85:
                reason=read(out/"decision.json")["fallback_reason"]
            elif rc not in (0,10,5):
                reason="native_restore_failed_exit_"+str(rc)
            else:
                try:
                    classify((cand/"result.json").read_bytes(),rc,phi)
                    if not read(cand/"native-stats.json")["checkpoint_used"]:
                        reason="missing_native_restore_confirmation"
                except (OSError,ValueError,KeyError):
                    reason="incomplete_candidate_result_after_restore"
        else:
            reason=old_stats["fallback_reason"] or reason or "checkpoint_unavailable"
        if reason:
            # Keep a failed native attempt available for diagnosis. The fallback
            # starts from pristine files in a fresh process under the same budget.
            if (cand/"result.json").exists() or (cand/"metrics.json").exists():
                cand.rename(out/"rejected-candidate")
                cand.mkdir()
                for f in ("program.c","harness.c"):shutil.copyfile(working/f,cand/f)
            verifier=start(cand)
            rc=verifier.wait(timeout=remaining())
        res,row=classify((cand/"result.json").read_bytes(),rc,phi)
        wall=time.monotonic()-update_start
        stats=read(cand/"native-stats.json") if not reason else {
            "checkpoint_used":False,"reused_prefix_symex_steps":0,
            "executed_symex_steps":read(cand/"metrics.json")["symbolic_instruction_dispatches"],"sc_counters":{}}
        summary={"case":case.name,"path":"full_fallback" if reason else "incremental","fallback_reason":reason,
                 "old":old_result,"candidate":res,"candidate_exit":rc,"old_exit":old_exit,
                 "old_trace_steps":len(old_target.get("trace",[])),"candidate_trace_steps":len(row.get("trace",[])),
                 "native":{k:v for k,v in stats.items() if k!="executed_dispatches"},
                 "old_native":{k:v for k,v in old_stats.items() if k!="executed_dispatches"},
                 "checkpoint":ready,"old_warmup_wall_seconds":warmup_wall,"candidate_wall_seconds":wall,
                 "candidate_frontend_wall_seconds":frontend_wall,"command":cmd,"tool":lock,
                 "old_version":versions[0]["version_sha256"] if versions else None,
                 "candidate_version":versions[1]["version_sha256"] if len(versions)==2 else None,
                 "inputs_sha256":{f:file_sha(cand/f) for f in ("program.c","harness.c")},"cgroup_bytes":int(memory_max())}
        save(out/"session.json",summary)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("case",choices=sorted(CASES))
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--case-dir", type=Path, help="use a separate copy of this case with its protected manifest")
    p.add_argument("--checkpoint-bytes",type=int,help="tighten the configured checkpoint memory limit")
    p.add_argument("--contained",action="store_true",help=argparse.SUPPRESS)
    a=p.parse_args()
    case = a.case_dir.resolve() if a.case_dir else CASES[a.case]
    if case.name != a.case:
        p.error("case directory must match the case identifier")
    if a.contained:
        s=run_pair(case,a.out.resolve(),checkpoint_bytes=a.checkpoint_bytes)
        print(s["case"],s["path"],s["fallback_reason"],s["candidate"]["classification"],
              s["native"]["reused_prefix_symex_steps"],s["native"]["executed_symex_steps"])
        return 0
    _,gamma,_=load_case(case)
    extra=[] if a.checkpoint_bytes is None else ["--checkpoint-bytes",str(a.checkpoint_bytes)]
    if a.case_dir:
        extra.extend(["--case-dir", str(case)])
    return subprocess.run(["systemd-run","--quiet","--pipe","--wait","--collect",
                           "-p","WorkingDirectory="+str(ROOT),"-p","MemoryMax="+str(gamma["limits"]["memory_bytes"]),
                           "--",sys.executable,"-B",str(Path(__file__).resolve()),a.case,"--out",str(a.out.resolve()),"--contained",*extra]).returncode
if __name__=="__main__":sys.exit(main())
