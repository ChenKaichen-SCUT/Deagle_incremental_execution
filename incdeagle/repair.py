"""Admit one source-only candidate against a newly observed old-program violation."""
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from incdeagle.counterexample import normalize
from incdeagle.model.identity import file_sha, read, save
from scripts.stage2.check_case import ROOT, load_case

PROTECTED = ("task.yaml", "harness.c", "phi.json", "gamma.json", "old/program.c")


class Outcome(Exception):
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status = status


def event(run, name, **details):
    row = {"event":name, "monotonic_ns":time.monotonic_ns(),
           "utc":datetime.now(timezone.utc).isoformat(), **details}
    with (run/"events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, sort_keys=True)+"\n")


def plain(path):
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode):
        raise ValueError("Expected a regular file: "+str(path))
    return path


def original_hashes(case):
    return {name:file_sha(plain(case/name)) for name in PROTECTED}


def inspect(case):
    manifest = yaml.safe_load(plain(case/"task.yaml").read_bytes())
    if (manifest["old_source"],manifest["candidate_source"],manifest["verification_config"],manifest["property"]["file"]) != (
            "old/program.c","candidate/program.c","gamma.json","phi.json"):
        raise ValueError("Unsupported case layout")
    _, gamma, phi = load_case(case)
    hashes = original_hashes(case)
    if (case/"freeze.json").is_file():
        fixed = read(case/"freeze.json")["files_sha256"]
        if any(fixed[name]!=value for name,value in hashes.items()):
            raise ValueError("Original input differs from the frozen case")
    return {"case":case.name, "protected_sha256":hashes, "property":phi, "configuration":gamma}


def git_patch(cwd, arguments, data=None):
    result = subprocess.run(["git","-C",str(cwd),"-c","core.autocrlf=false",*arguments],
                            input=data, capture_output=True, timeout=20)
    if result.returncode:
        raise Outcome("INVALID_PATCH","Git rejected the source diff: "+result.stderr.decode("utf-8","replace")[:400])
    return result.stdout


def apply_source_patch(source, patch):
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        git_patch(cwd,["init","--quiet"])
        file = cwd/"program.c"
        file.write_bytes(source)
        paths = git_patch(cwd,["apply","--numstat","-z","-"],patch).rstrip(b"\0").split(b"\0")
        if len(paths)!=1 or paths[0].split(b"\t")[2:]!=[b"program.c"] or re.search(
                rb"^(old mode|new mode|new file mode|deleted file mode|rename |copy |GIT binary patch)",patch,re.M):
            raise Outcome("INVALID_PATCH","The patch must edit only the existing regular program.c")
        git_patch(cwd,["apply","--check","-"],patch)
        git_patch(cwd,["apply","-"],patch)
        return plain(file).read_bytes()


def make_patch(source, candidate):
    if not candidate or source==candidate or b"\0" in candidate:
        raise Outcome("INVALID_PATCH","A nonempty C source change is required")
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path(tmp)
        git_patch(cwd,["init","--quiet"])
        path = cwd/"program.c"
        path.write_bytes(source)
        git_patch(cwd,["add","--","program.c"])
        path.write_bytes(candidate)
        patch = git_patch(cwd,["diff","--no-ext-diff","--no-color","--","program.c"])
    if apply_source_patch(source,patch)!=candidate:
        raise Outcome("INVALID_PATCH","Diff replay did not reproduce the submitted candidate bytes")
    return patch


def submit_manual(run, patch, trace_sha, note):
    """Atomically deliver one local author's response to this run's counterexample."""
    request = read(run/"request.json")
    if not request.get("wait_patch") or (run/"online-status.json").exists():
        raise ValueError("This run is not waiting for a manual submission")
    binding = read(run/"repair/input.json")
    if trace_sha!=binding["normalized_trace_sha256"]:
        raise ValueError("Submission refers to a different P0 trace")
    body = plain(patch).read_bytes()
    response = {"run_id":request["run_id"], "normalized_trace_sha256":trace_sha,
                "p0_sha256":binding["protected_sha256"]["old/program.c"],
                "patch_sha256":hashlib.sha256(body).hexdigest(),"diff":body.decode("utf-8"),
                "note":note,"submitted_utc":datetime.now(timezone.utc).isoformat(),
                "submitted_monotonic_ns":time.monotonic_ns()}
    target = run/"repair/manual-submission.json"
    with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as tmp:
        tmp.write(json.dumps(response,ensure_ascii=False).encode("utf-8"))
    try:
        os.link(tmp.name,target)
    finally:
        Path(tmp.name).unlink()
    return {"run_id":request["run_id"],"patch_sha256":response["patch_sha256"]}


def review(source, candidate, case):
    # Explicitly flag common ways to bypass the benchmark contract. Other edits
    # still go through the complete protected property on both model checkers.
    check = rb"\b(?:__CPROVER_assume|__VERIFIER_assume|abort|exit|_Exit|longjmp|pthread_exit)\s*\("
    if len(re.findall(check,candidate))>len(re.findall(check,source)) or re.search(rb"(?m)^\s*#\s*(?:define|undef)\s+(?:assert|main)\b", candidate):
        raise Outcome("INVALID_PATCH","Candidate introduces a verification or control-flow bypass")
    if case=="batch_total" and re.search(rb"\bshipped_units\s*=\s*\d+\s*;",candidate):
        raise Outcome("INVALID_PATCH","Candidate replaces batch accumulation with a fixed total")


class CandidateProvider:
    def __init__(self, run, case, request):
        self.run = run
        self.case = case
        self.request = request
        self.repair = run/"repair"
        self.repair.mkdir()
        self.initial = request["protected_sha256"]
        self.source_case = Path(request["case_dir"])
        self.task, self.gamma, self.phi = load_case(case)

    def intact(self):
        if original_hashes(self.case)!=self.initial or original_hashes(self.source_case)!=self.initial:
            raise Outcome("ERROR","Original program, property or verification configuration changed")

    def propose(self, old):
        method = self.request["repair"]
        if method=="manual":
            if self.request.get("wait_patch"):
                path = self.repair/"manual-submission.json"
                limit = self.request["repair_timeout_seconds"]
                before = time.monotonic()
                while not path.is_file():
                    if time.monotonic()-before>=limit:
                        raise Outcome("REPAIR_FAILED","Timed out waiting for one local manual patch")
                    time.sleep(.05)
                submission = read(path)
                binding = read(self.repair/"input.json")
                patch = submission["diff"].encode("utf-8")
                if (submission["run_id"]!=self.request["run_id"] or
                        submission["normalized_trace_sha256"]!=binding["normalized_trace_sha256"] or
                        submission["p0_sha256"]!=self.initial["old/program.c"] or
                        submission["patch_sha256"]!=hashlib.sha256(patch).hexdigest()):
                    raise Outcome("INVALID_PATCH","Manual submission has stale source, trace or patch identity")
                source = "manual_after_live_counterexample"
                event(self.run,"manual_patch_received",patch_sha256=submission["patch_sha256"],
                      trace_sha256=submission["normalized_trace_sha256"])
            else:
                patch = plain(Path(self.request["patch"])).read_bytes()
                source = "supplied_unified_diff"
            (self.repair/"submitted.diff").write_bytes(patch)
            return apply_source_patch(old,patch), {"source":source,"api_calls":0}
        if method=="replay":
            prior = self.request.get("from_run")
            if prior:
                prior = Path(prior)
                frozen = read(prior/"frozen.json")
                if frozen["case"]!=self.case.name or frozen["protected_sha256"]!=self.initial:
                    raise Outcome("INVALID_PATCH","The archived candidate belongs to different protected inputs")
                path = prior/"snapshot"/self.case.name/"candidate/program.c"
                expected = frozen["candidate_sha256"]
            else:
                path = self.source_case/"candidate/program.c"
                expected = (read(self.source_case/"freeze.json")["files_sha256"]["candidate/program.c"]
                            if (self.source_case/"freeze.json").is_file() else self.request["replay_input_sha256"])
            data = plain(path).read_bytes()
            if hashlib.sha256(data).hexdigest()!=expected:
                raise Outcome("INVALID_PATCH","The supplied replay bytes differ from their frozen hash")
            return data, {"source":"previous_run" if prior else "case_snapshot","api_calls":0,
                          "replay_source_sha256":expected}
        executable = ROOT/".venv/bin/python"
        command = [str(executable),"-B",str(ROOT/"scripts/stage6/mini_repair.py"),str(self.run)]
        if self.request["key_stdin"]:
            command.append("--key-stdin")
        clean_config = self.repair/"controller-config"
        clean_config.mkdir(mode=0o700)
        worker_env = {"PATH":"/usr/local/bin:/usr/bin:/bin","LC_ALL":"C.UTF-8",
                      "MSWEA_GLOBAL_CONFIG_DIR":str(clean_config),"MSWEA_SILENT_STARTUP":"1",
                      "DO_NOT_TRACK":"1","LITELLM_TELEMETRY":"False"}
        save(self.repair/"mini-start.json",{"started":True})
        try:
            cfg = yaml.safe_load((ROOT/"configs/deepseek.yaml").read_bytes())
            result = subprocess.run(command,stdin=None if self.request["key_stdin"] else subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=worker_env,
                                    timeout=cfg["repair"]["timeout_seconds"]+30)
        except (OSError,subprocess.TimeoutExpired) as error:
            raise Outcome("REPAIR_FAILED","mini worker: "+type(error).__name__) from error
        metadata = read(self.repair/"model.json") if (self.repair/"model.json").is_file() else {}
        if result.returncode or metadata.get("exit_status")!="Submitted":
            reason = metadata.get("error_reason") or metadata.get("error","mini did not return a submitted candidate")
            raise Outcome("REPAIR_FAILED",reason)
        path = plain(self.repair/"submitted.c")
        if file_sha(path)!=metadata["candidate_sha256"]:
            raise Outcome("INVALID_PATCH","Submitted mini output failed its content check")
        return path.read_bytes(), {"source":"mini_deepseek","api_calls":len(metadata["requests"]),
                                   "model":metadata["model"],"model_record":"repair/model.json"}

    def produce(self, old, verdict, target, checkpoint, process, warmup_wall):
        self.intact()
        if file_sha(old/"program.c")!=self.initial["old/program.c"] or file_sha(old/"harness.c")!=self.initial["harness.c"]:
            raise Outcome("ERROR","The native P0 inputs differ from the protected snapshot")
        hashes = {"program.c":self.initial["old/program.c"], **{k:v for k,v in self.initial.items() if k!="old/program.c"}}
        trace = normalize(target,self.phi,self.gamma,hashes,"../pair/old/result.json")
        save(self.repair/"cex0.json",trace)
        pid = checkpoint.get("checkpoint_pid")
        def live():
            return bool(pid==process.pid and process.poll() is None)
        binding = {"old_pid":checkpoint.get("old_pid"),"checkpoint_pid":pid,"checkpoint_available":bool(checkpoint),
                   "checkpoint_live_before_repair":live(),"old_warmup_seconds":warmup_wall,
                   "old_version":read(old/"manifest.json")["version_sha256"],"old_result":verdict,
                   "normalized_trace_sha256":file_sha(self.repair/"cex0.json"),"raw_trace_sha256":file_sha(old/"result.json"),
                   "trace_steps":trace["step_count"],"old_cache_sha256":file_sha(old/"lemma-cache.json"),
                   "old_exported":read(old/"theory-export.json")["exported"],"protected_sha256":self.initial}
        save(self.repair/"input.json",binding)
        event(self.run,"old_violation_and_cache_ready",**binding)
        event(self.run,"repair_started",method=self.request["repair"])
        begin = time.monotonic_ns()
        source = plain(self.case/"old/program.c").read_bytes()
        data, metadata = self.propose(source)
        patch = make_patch(source,data)
        (self.repair/"patch.diff").write_bytes(patch)
        self.intact()
        review(source,data,self.case.name)
        final = self.case/"candidate/program.c"
        final.parent.mkdir()
        with final.open("xb") as destination:
            destination.write(data)
        final.chmod(0o444)
        self.seal = {"case":self.case.name,"candidate_sha256":file_sha(final),"patch_sha256":file_sha(self.repair/"patch.diff"),
                     "protected_sha256":self.initial,"change_allowlist":["program.c"],"patch_reapplied_byte_for_byte":True,
                     "method":self.request["repair"],"old_version":binding["old_version"],"metadata":metadata,
                     "checkpoint_pid":pid,"checkpoint_live_after_repair":live(),"repair_elapsed_ns":time.monotonic_ns()-begin}
        if binding["checkpoint_live_before_repair"] and not self.seal["checkpoint_live_after_repair"]:
            raise Outcome("ERROR","The native checkpoint exited during candidate generation")
        save(self.repair/"proposal.json",self.seal)
        event(self.run,"single_candidate_sealed",candidate_sha256=self.seal["candidate_sha256"],
              checkpoint_pid=pid,checkpoint_live=live())

    def admit(self, front, exit_code):
        self.intact()
        if exit_code or not (front/"goto.irep").is_file() or not (front/"goto.json").is_file():
            if exit_code in (-9,137,124):
                raise Outcome("TIMEOUT" if exit_code==124 else "ERROR",f"Candidate frontend terminated, exit {exit_code}")
            diagnostics = (front/"diagnostic.stderr").read_bytes()+(front/"diagnostic.stdout").read_bytes()
            errors = []
            if (front/"result.json").is_file():
                try:
                    document = read(front/"result.json")
                except ValueError:
                    document = []
                errors = [row for row in document if isinstance(row,dict) and row.get("messageType")=="ERROR"]
                diagnostics += "\n".join(str(row.get("messageText","")) for row in errors).encode()
            parsed = any(marker in diagnostics.lower() for marker in
                         (b"parsing error",b"typechecking error",b"conversion error",b"syntax error"))
            reason = f"Candidate Deagle frontend failed, exit {exit_code}"
            if errors:
                row = errors[0]
                location = row.get("sourceLocation",{})
                reason += f" ({location.get('file','?')}:{location.get('line','?')}, {row.get('messageText','')})"
            raise Outcome("INVALID_PATCH" if parsed else "ERROR",reason)
        goto = read(front/"goto.json")
        where = self.phi["source"]
        matches = [r for r in goto["instructions"] if r["kind"]=="ASSERT"
                   and all(str(r[k])==str(where[k]) for k in ("function","file","line"))]
        if len(matches)!=1:
            raise Outcome("INVALID_PATCH","The protected target assertion is missing or ambiguous in candidate GOTO")
        for where_dir in (front, front.parent/"candidate", front.parent/"source"):
            if file_sha(where_dir/"program.c")!=self.seal["candidate_sha256"] or file_sha(where_dir/"harness.c")!=self.initial["harness.c"]:
                raise Outcome("ERROR","Candidate inputs differ before native update")
        self.seal.update(frontend_exit=exit_code,goto_image_sha256=file_sha(front/"goto.irep"),
                         assertion_sha256=self.phi["assertion_sha256"],frontend_target=self.phi["source"])
        save(self.run/"frozen.json",self.seal)
        event(self.run,"candidate_frontend_admitted",candidate_sha256=self.seal["candidate_sha256"],
              target=self.phi["id"],goto_sha256=self.seal["goto_image_sha256"])
