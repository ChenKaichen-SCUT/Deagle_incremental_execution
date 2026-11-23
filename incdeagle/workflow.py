"""Coordinate one live repair and one independent verification of its sealed candidate."""
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
import yaml

from incdeagle.adapters.deagle import classify
from incdeagle.comparison import bounded, compare, full_candidate, model_check
from incdeagle.counterexample import normalize
from incdeagle.model.identity import file_sha, read, save
from incdeagle.repair import CandidateProvider, Outcome, PROTECTED, event, inspect, original_hashes
from scripts.stage2.check_case import BINARY, ROOT, load_case
from scripts.stage4.session import run_pair
from scripts.stage5.session import TheorySession, summarize_theory


def doctor():
    lock = read(TheorySession.release_lock)
    tools = {}
    for name,exe in (("development",TheorySession.binary),("baseline",BINARY)):
        tree = exe.parents[2]
        commit = (subprocess.run(["git","-C",str(tree),"rev-parse","HEAD"],capture_output=True,text=True).stdout.strip()
                  if tree.is_dir() else None)
        sha = file_sha(exe) if exe.is_file() else None
        tools[name] = {"file":str(exe),"commit":commit,"sha256":sha,
                       "matches_lock":sha==lock[name+"_sha256"] and commit==lock[name+"_commit"]}
    available = {k:shutil.which(k) for k in ("systemd-run","git","gcc","bwrap","setpriv")}
    ready = all(v["matches_lock"] for v in tools.values()) and all(available[k] for k in ("systemd-run","git","gcc"))
    return {"native_ready":bool(ready),"binaries":tools,"commands":available,
            "mini_python":(ROOT/".venv/bin/python").is_file(),"controller_key_file_exists":(ROOT/"apikey.txt").is_file(),
            "model_config":"configs/deepseek.yaml","verification_lock":"configs/stage05.lock.json"}


def oom_count():
    try:
        group = next(x.split("::",1)[1] for x in Path("/proc/self/cgroup").read_text().splitlines() if x.startswith("0::"))
        fields = dict(line.split() for line in (Path("/sys/fs/cgroup")/group.lstrip("/")/"memory.events").read_text().splitlines())
        return int(fields["oom_kill"])
    except (OSError,StopIteration,ValueError,KeyError):
        return None


def online(run):
    request = read(run/"request.json")
    case = run/"snapshot"/request["case"]
    pair = run/"pair"
    before = oom_count()
    try:
        provider = CandidateProvider(run,case,request)
        session = run_pair(case,pair,theory=TheorySession(),candidate_provider=provider)
        if session["candidate"] is None:
            event(run,"old_not_violation",result=session["old"])
            status = {"status":"OLD_NOT_VIOLATION","old":session["old"]}
        else:
            provider.intact()
            theory = summarize_theory(pair)
            verdict = session["candidate"]
            if verdict["classification"]=="VIOLATION":
                raw = pair/"candidate/result.json"
                _,row = classify(raw.read_bytes(),session["candidate_exit"],provider.phi)
                save(pair/"candidate/cex1.json",normalize(row,provider.phi,provider.gamma,session["inputs_sha256"],
                                                         "result.json",version="candidate"))
            status = {"status":"VERIFIED","result":verdict,"theory":theory}
    except (Outcome,ValueError,TypeError,KeyError,RuntimeError,OSError,subprocess.SubprocessError) as exc:
        code = exc.status if isinstance(exc,Outcome) else "ERROR"
        if isinstance(exc,(TimeoutError,subprocess.TimeoutExpired)):
            code = "TIMEOUT"
        after = oom_count()
        if before is not None and after is not None and after>before:
            code = "OOM"
        status = {"status":code,"reason":str(exc),"error_type":type(exc).__name__}
    save(run/"online-status.json",status)
    event(run,"native_session_returned",status=status["status"])


def snapshot(case, run):
    identity = inspect(case)
    target = run/"snapshot"/case.name
    for name in PROTECTED:
        dst = target/name
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(case/name,dst)
        dst.chmod(0o444)
    if original_hashes(target)!=identity["protected_sha256"]:
        raise ValueError("Unstable old inputs during staging")
    return identity,target


def repair_cost(run, method):
    if (run/"repair/model.json").is_file():
        data = read(run/"repair/model.json")
        calls = data["requests"]
        measured = all("input_tokens" in r and "output_tokens" in r for r in calls)
        return {"model":data.get("model"),"api_calls":len(calls),"input_tokens":sum(r["input_tokens"] for r in calls) if measured else None,
                "output_tokens":sum(r["output_tokens"] for r in calls) if measured else None,
                "estimated_usd_by_tariff":data["estimated_usd_by_tariff"]}
    attempted = method=="mini" and (run/"repair/mini-start.json").exists()
    return {"api_calls":None if attempted else 0,"input_tokens":None if attempted else 0,
            "output_tokens":None if attempted else 0,"estimated_usd":None if attempted else 0}


def execute(case_path, *, method, out=None, patch=None, from_run=None, key_stdin=False, check_model=False,
            wait_patch=False, repair_input_sha256=None):
    manifest = case_path.resolve()
    if manifest.name!="task.yaml" or not manifest.is_file():
        raise ValueError("Pass the case's task.yaml")
    case = manifest.parent
    identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+"-"+uuid.uuid4().hex[:8]
    run = (out if out is not None else ROOT/"runs/stage-06"/(identifier+"-"+case.name)).resolve()
    if run==case or case in run.parents:
        raise ValueError("Use a separate output directory outside the case")
    run.mkdir(parents=True,exist_ok=False)
    result = {"schema":1,"case":case.name,"method":method,"run_id":identifier,"status":"STARTED",
              "agreement":None,"baseline_started":False,"model_check_requested":check_model}
    save(run/"workflow.json",result)
    start = time.monotonic_ns()
    try:
        identity,staged = snapshot(case,run)
        repair_limits = yaml.safe_load((ROOT/"configs/deepseek.yaml").read_bytes())["repair"]
        request = {"case":case.name,"case_dir":str(case),"repair":method,"key_stdin":key_stdin,
                   "run_id":identifier,"wait_patch":wait_patch,"repair_timeout_seconds":repair_limits["timeout_seconds"],
                   "protected_sha256":identity["protected_sha256"],"property":identity["property"]["id"]}
        if repair_input_sha256:
            request["repair_input_sha256"] = repair_input_sha256
        if method=="manual" and not wait_patch:
            request["patch"] = str((patch or case/"patch.diff").resolve())
        if method=="replay":
            if from_run:
                request["from_run"] = str(from_run.resolve())
            else:
                request["replay_input_sha256"] = file_sha(case/"candidate/program.c")
        save(run/"request.json",request)
        event(run,"old_snapshot_staged",protected_sha256=request["protected_sha256"])
        iso = run/"online-service"
        iso.mkdir()
        limits = identity["configuration"]["limits"]
        # The P0 and P1 verification budgets are independent of the single repair budget.
        repair_budget = repair_limits["timeout_seconds"] if method=="mini" or wait_patch else 0
        event(run,"native_session_started")
        cmd = [sys.executable,"-B","-m","incdeagle.cli","_online",str(run)]
        svc = bounded(cmd,ROOT,iso,limits,stdin=None if key_stdin else subprocess.DEVNULL,
                      seconds=2*limits["timeout_seconds"]+repair_budget+60)
        if (run/"online-status.json").is_file():
            state = read(run/"online-status.json")
        else:
            state = {"status":svc["resource_status"] or "ERROR","reason":"Online service exited before writing its status",
                     "exit_code":svc["exit_code"]}
        event(run,"native_session_closed",status=state["status"],service_exit=svc["exit_code"])
        result.update(online_status=state["status"],online_service_ns=svc["wall_ns"],
                      online_reason=state.get("reason"),protected_sha256=request["protected_sha256"])
        if (run/"repair/input.json").is_file():
            inp = read(run/"repair/input.json")
            result.update(old=inp["old_result"],old_trace_steps=inp["trace_steps"],old_warmup_seconds=inp["old_warmup_seconds"])
        if state["status"]=="OLD_NOT_VIOLATION":
            result.update(old=state["old"],status="OLD_NOT_VIOLATION")
        elif not (run/"frozen.json").is_file():
            result["status"]=state["status"] if state["status"]!="VERIFIED" else "ERROR"
        else:
            frozen = read(run/"frozen.json")
            intact = (original_hashes(case)==original_hashes(staged)==frozen["protected_sha256"] and
                      file_sha(staged/"candidate/program.c")==frozen["candidate_sha256"])
            if not intact:
                raise ValueError("Protected inputs or sealed candidate changed after the session")
            if state["status"]=="VERIFIED":
                session = read(run/"pair/session.json")
                if session["inputs_sha256"]!={"harness.c":request["protected_sha256"]["harness.c"],"program.c":frozen["candidate_sha256"]}:
                    raise ValueError("Online solver reports different candidate inputs")
                online_result = session["candidate"]
                result.update(model_path=session["path"],fallback_reason=session["fallback_reason"],
                              native=session["native"],theory=state["theory"],candidate_trace_steps=session["candidate_trace_steps"],
                              old_version=session["old_version"],new_version=session["candidate_version"],
                              online_candidate_seconds=session["candidate_wall_seconds"],frontend_seconds=session["candidate_frontend_wall_seconds"])
            else:
                online_result = {"classification":state["status"],"reason":state.get("reason")}
            result.update(candidate_sha256=frozen["candidate_sha256"],repair_elapsed_ns=frozen["repair_elapsed_ns"],
                          online=online_result,baseline_started=True)
            event(run,"independent_full_started",candidate_sha256=frozen["candidate_sha256"])
            baseline = full_candidate(run,staged,frozen)
            result["baseline"]=baseline
            agreement = compare(online_result,baseline["result"])
            result.update(agreement=agreement,status="COMPLETED" if agreement=="DEFINITE_AGREEMENT" else agreement)
            event(run,"independent_full_finished",classification=baseline["result"]["classification"],agreement=agreement)
            if check_model and agreement=="DEFINITE_AGREEMENT":
                event(run,"model_diagnostic_started")
                diagnostic = full_candidate(run,staged,frozen,diagnostic=True)
                if diagnostic["result"]["classification"] in ("ERROR","TIMEOUT","OOM","UNKNOWN"):
                    result.update(status="DIAGNOSTIC_INCOMPLETE",diagnostic=diagnostic)
                else:
                    record = model_check(run,staged,session,state["theory"],diagnostic)
                    result["model_match"]=record["match"]
                    if not record["match"]:
                        result["status"]="MODEL_MISMATCH"
                event(run,"model_diagnostic_finished",status=result["status"])
            if original_hashes(case)!=request["protected_sha256"] or original_hashes(staged)!=request["protected_sha256"]:
                raise ValueError("Protected inputs changed during independent comparison")
    except (ValueError,RuntimeError,KeyError,TypeError,OSError,subprocess.SubprocessError) as exc:
        result.update(status="ERROR",reason=str(exc),error_type=type(exc).__name__)
    finally:
        result["repair_usage"] = repair_cost(run,method)
        result["elapsed_ns"] = time.monotonic_ns()-start
        event(run,"workflow_finished",status=result["status"])
        save(run/"workflow.json",result)
    return run,result
