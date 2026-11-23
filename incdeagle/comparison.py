"""Run an isolated full oracle after the online session, then compare the same property."""
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from incdeagle.adapters.deagle import classify
from incdeagle.counterexample import normalize
from incdeagle.model.compare import delta
from incdeagle.model.identity import file_sha, read, save
from incdeagle.model.observe import build_model
from incdeagle.model.repeat import phase_digest
from scripts.stage2.check_case import BINARY, ROOT, load_case
from scripts.stage5.session import TheorySession
from scripts.stage5.verify import check_native_imports

DEFINITE = {"VIOLATION","NO_VIOLATION_WITHIN_BOUND","SAFE"}


def bounded(argv, cwd, output, limits, *, env=None, stdin=subprocess.DEVNULL, seconds=None):
    unit = "incdeagle6-"+uuid.uuid4().hex
    command = ["systemd-run","--quiet","--wait","--pipe","--collect","--unit",unit,
               "-p","WorkingDirectory="+str(cwd),"-p","MemoryMax="+str(limits["memory_bytes"]),"--setenv=LC_ALL=C"]
    command.extend("--setenv="+k+"="+str(v) for k,v in (env or {}).items())
    command.extend(["--","/usr/bin/timeout","--kill-after=5",str(seconds or limits["timeout_seconds"]),*map(str,argv)])
    start = time.monotonic_ns()
    with (output/"diagnostic.stdout").open("wb") as out, (output/"diagnostic.stderr").open("wb") as err:
        rc = subprocess.run(command,stdout=out,stderr=err,stdin=stdin).returncode
    ns = time.monotonic_ns()-start
    resource = "TIMEOUT" if rc==124 else None
    if rc not in (0,5,10):
        journal = subprocess.run(["journalctl","--no-pager","-o","cat","-u",unit+".service"],
                                 capture_output=True,timeout=12)
        lower = journal.stdout.lower()
        if b"oom-kill" in lower or b"oom killer" in lower or b"out of memory" in lower:
            resource = "OOM"
        # Only the resource indication is retained; the service's diagnostic streams are separate.
    receipt = {"command":command,"exit_code":rc,"wall_ns":ns,"resource_status":resource,"unit":unit}
    save(output/"command.json",receipt)
    return receipt


def full_candidate(run, case, frozen, *, diagnostic=False):
    _, gamma, phi = load_case(case)
    dest = run/("full-model" if diagnostic else "baseline")
    dest.mkdir()
    started = time.monotonic_ns()
    for name,input_file in (("program.c",case/"candidate/program.c"),("harness.c",case/"harness.c")):
        shutil.copyfile(input_file,dest/name)
    hashes = {"program.c":file_sha(dest/"program.c"),"harness.c":file_sha(dest/"harness.c")}
    if hashes!={"program.c":frozen["candidate_sha256"],"harness.c":frozen["protected_sha256"]["harness.c"]}:
        raise ValueError("Inputs passed to full verification differ from the admitted candidate")
    binary = TheorySession.binary if diagnostic else BINARY
    lock = read(TheorySession.release_lock)
    sha = file_sha(binary)
    if sha!=lock["development_sha256" if diagnostic else "baseline_sha256"]:
        raise ValueError("Unexpected full verification executable")
    env = {"INCDEAGLE_JSON_OUTPUT":dest/"result.json"}
    if diagnostic:
        env["INCDEAGLE_OBSERVE_DIR"] = dest
    argv = [binary,*gamma["source_argv"],*gamma["verification_output"],"harness.c"]
    receipt = bounded(argv,dest,dest,gamma["limits"],env=env)
    status = receipt["resource_status"]
    result = {"classification":status or "ERROR","target":phi["id"],"target_source":phi["source"]}
    if not status and receipt["exit_code"] in (0,5,10):
        try:
            raw = (dest/"result.json").read_bytes()
            result,target = classify(raw,receipt["exit_code"],phi)
            output = (dest/"diagnostic.stdout").read_bytes()
            if receipt["exit_code"] in (0,10) and not all(marker in output for marker in
                    (b"Use Deagle's closure solver", b"Set Deagle closure solver's graph")):
                raise ValueError("Missing native Closure backend markers")
            if result["classification"]=="VIOLATION":
                cex = normalize(target,phi,gamma,hashes,"result.json",version="candidate")
                save(dest/"cex1.json",cex)
        except (OSError,ValueError,KeyError) as exc:
            result = {"classification":"ERROR","reason":str(exc),"target":phi["id"],"target_source":phi["source"]}
    record = {"result":result,"input_sha256":hashes,"phi_sha256":file_sha(case/"phi.json"),
              "gamma_sha256":file_sha(case/"gamma.json"),"binary_sha256":sha,
              "wall_ns":time.monotonic_ns()-started,"exit_code":receipt["exit_code"]}
    save(dest/"verification.json",record)
    return record


def compare(online, baseline):
    a,b = online["classification"],baseline["classification"]
    if a not in DEFINITE or b not in DEFINITE:
        return "INCONCLUSIVE"
    if (a=="VIOLATION")!=(b=="VIOLATION"):
        return "DEFINITE_CONFLICT"
    if any(online.get(k)!=baseline.get(k) for k in ("target","properties","unwinding_properties","target_source")):
        return "PROPERTY_DETAILS_DIFFER"
    return "DEFINITE_AGREEMENT"


def model_check(run, case, session, theory, full):
    pair, fresh = run/"pair", run/"full-model"
    old, new = pair/"old", pair/"candidate"
    target = session["candidate"]["target"]
    phases = {name:{k:phase_digest(read(path/(name+".json"))) for k,path in (("online",new),("full",fresh))}
              for name in ("goto","raw_ssa","sc_input","full_model")}
    models = {k:build_model(path,target) for k,path in (("old",old),("online",new),("full",fresh))}
    p0,p1 = read(old/"manifest.json"),read(pair/"frontend/manifest.json")
    changes = delta(models["old"],models["online"],p0,p1)
    changes.update(purpose="post-run model diagnostic",old_version=p0["version_sha256"],new_version=p1["version_sha256"])
    save(run/"model-delta.json",changes)
    trace = [{k:v[k] for k in ("thread","function","pc")} for v in read(fresh/"visits.json")]
    n = session["native"]
    skipped,executed = n["reused_prefix_symex_steps"],n["executed_symex_steps"]
    dispatch_ok = len(trace)==skipped+executed
    if n["checkpoint_used"]:
        old_trace = read(old/"native-stats.json")["executed_dispatches"]
        new_trace = read(new/"native-stats.json")["executed_dispatches"]
        dispatch_ok = dispatch_ok and old_trace[:skipped]+new_trace==trace and executed==len(new_trace)
    digests = {k:models[k]["structure_sha256"] for k in ("online","full")}
    graph = read(old/"theory-export.json")
    imports = []
    if graph["snapshot_error"] is None and (new/"theory-context.json").is_file() and read(new/"native-plan.json")["valid_plan"]:
        fresh_solvers, imports = check_native_imports(pair,theory)
    elif theory["imported"]:
        raise ValueError("Cannot replay the claimed nonzero native imports")
    else:
        fresh_solvers = {v:read(pair/v/"fresh-solver.json") for v in ("old","candidate")}
    ok = (dispatch_ok and digests["online"]==digests["full"] and all(p["online"]==p["full"] for p in phases.values())
          and full["result"]==session["candidate"] and p0["version_sha256"]==session["old_version"]
          and p1["version_sha256"]==session["candidate_version"])
    record = {"match":ok,"phase_digests":phases,"model_digests":digests,"full_dispatches":len(trace),
              "native_skipped":skipped,"native_executed":executed,"dispatch_accounting":dispatch_ok,
              "old_version":p0["version_sha256"],"new_version":p1["version_sha256"],
              "native_imports_checked":imports,"fresh_solvers":fresh_solvers}
    save(run/"model-check.json",record)
    return record
