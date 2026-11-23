#!/usr/bin/env python3
"""Verify Stage 6 from the published archive using Python's standard library and Git."""
import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.adapters.deagle import classify
from incdeagle.counterexample import normalize
from incdeagle.model.identity import digest, file_sha, read
from incdeagle.model.repeat import phase_digest
from incdeagle.repair_input import make_packet, packet_sha, wire_text
from incdeagle.theory.certificate import check
from incdeagle.theory.cache import validate
from incdeagle.theory.context import freeze
from scripts.stage6.mini_tools import INSTRUCTIONS, SYSTEM

EVIDENCE=ROOT/"reports/evidence/stage-06"


def require(value, reason):
    if not value:
        raise ValueError(reason)


def unpack(dest):
    index=read(EVIDENCE/"archive.json")
    archive=EVIDENCE/"full-runs.tar.gz"
    require(index["archive"]==archive.name and index["bytes"]==archive.stat().st_size and
            index["sha256"]==file_sha(archive),"Archive checksum")
    seen=set()
    with tarfile.open(archive,"r|gz") as t:
        for entry in t:
            name=PurePosixPath(entry.name)
            require(entry.isfile() and entry.name==name.as_posix() and not name.is_absolute() and
                    ".." not in name.parts and "\\" not in entry.name and ":" not in entry.name and
                    entry.name not in seen and entry.name in index["files"],entry.name)
            data=t.extractfile(entry).read()
            require(hashlib.sha256(data).hexdigest()==index["files"][entry.name],entry.name)
            p=dest.joinpath(*name.parts)
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_bytes(data)
            seen.add(entry.name)
    require(seen==set(index["files"]),"Missing archive members")
    return len(seen)


def timeline(run):
    events=[json.loads(x) for x in (run/"events.jsonl").read_text(encoding="utf-8").splitlines()]
    times=[e["monotonic_ns"] for e in events]
    require(times==sorted(times) and len(times)==len(set(times)),"Timeline not strictly ordered")
    return events


def signed(reg, clause):
    by_slot={slot:raw for _,raw,slot in reg.by_key.values()}
    return [by_slot[slot]^sign for slot,sign in reg.bind(clause)]


def verify_run(run, summary, lock):
    w=read(run/"workflow.json")
    pair,base=run/"pair",run/"baseline"
    s=read(pair/"session.json")
    name=w["case"]
    snap=run/"snapshot"/name
    orig=(ROOT/"tests/stage3"/name) if name=="partial_counter" else (ROOT/"cases"/name)
    frozen=read(run/"frozen.json")
    h=frozen["protected_sha256"]
    require(w["status"]=="COMPLETED" and w["agreement"]=="DEFINITE_AGREEMENT" and
            all(file_sha(snap/k)==file_sha(orig/k)==sha for k,sha in h.items()),name+" protected inputs")
    sha=frozen["candidate_sha256"]
    require(all(file_sha(p)==sha for p in (snap/"candidate/program.c",pair/"candidate/program.c",
                pair/"frontend/program.c",base/"program.c",run/"full-model/program.c")),name+" different candidate bytes")
    phi,gamma=read(snap/"phi.json"),read(snap/"gamma.json")
    before=read(run/"repair/input.json")
    before_hash={"program.c":h["old/program.c"],**{k:v for k,v in h.items() if k!="old/program.c"}}
    old,target=classify((pair/"old/result.json").read_bytes(),s["old_exit"],phi)
    require(old==before["old_result"]==w["old"] and old["classification"]=="VIOLATION",name+" P0 property")
    cex=normalize(target,phi,gamma,before_hash,"../pair/old/result.json")
    require(cex==read(run/"repair/cex0.json") and file_sha(run/"repair/cex0.json")==before["normalized_trace_sha256"]
            and file_sha(pair/"old/result.json")==before["raw_trace_sha256"],name+" P0 trace")
    ev=timeline(run)
    order=[e["event"] for e in ev]
    need=["old_snapshot_staged","native_session_started","old_violation_and_cache_ready","repair_started",
          "single_candidate_sealed","candidate_frontend_admitted","native_session_returned","native_session_closed",
          "independent_full_started","independent_full_finished","model_diagnostic_started","model_diagnostic_finished","workflow_finished"]
    require(all(order.count(x)==1 for x in need) and [order.index(x) for x in need]==sorted(order.index(x) for x in need),
            name+" online/full ordering")
    ready=read(pair/"old_done.json")
    require(ready["checkpoint_pid"]==frozen["checkpoint_pid"]==before["checkpoint_pid"] and
            before["checkpoint_live_before_repair"] and frozen["checkpoint_live_after_repair"] and
            read(pair/"old/fresh-solver.json")["pid"]==ready["old_pid"],name+" live handoff")
    if frozen["metadata"]["source"]=="manual_after_live_counterexample":
        response=read(run/"repair/manual-submission.json")
        e={x["event"]:x for x in ev}
        require(e["repair_started"]["monotonic_ns"]<=response["submitted_monotonic_ns"]<=e["manual_patch_received"]["monotonic_ns"]
                and response["normalized_trace_sha256"]==before["normalized_trace_sha256"]
                and response["patch_sha256"]==file_sha(run/"repair/submitted.diff") and
                response["run_id"]==w["run_id"],name+" live response")
    patch=run/"repair/patch.diff"
    require(file_sha(patch)==frozen["patch_sha256"],name+" patch hash")
    with tempfile.TemporaryDirectory() as tmp:
        cwd=Path(tmp)
        (cwd/"program.c").write_bytes((snap/"old/program.c").read_bytes())
        subprocess.run(["git","init","-q",str(cwd)],check=True)
        subprocess.run(["git","-C",str(cwd),"-c","core.autocrlf=false","apply",str(patch)],check=True)
        require(file_sha(cwd/"program.c")==sha and {p.name for p in cwd.iterdir()}=={".git","program.c"},name+" patch replay")

    baseline=read(base/"verification.json")
    require(baseline["binary_sha256"]==lock["baseline_sha256"] and s["tool"]["development_sha256"]==lock["development_sha256"]
            and s["tool"]["commit"]==lock["development_commit"],name+" locked binaries")
    require(baseline["phi_sha256"]==h["phi.json"] and baseline["gamma_sha256"]==h["gamma.json"] and
            baseline["input_sha256"]==s["inputs_sha256"]=={"program.c":sha,"harness.c":h["harness.c"]},name+" same configuration")
    command=read(base/"command.json")["command"]
    cut=command.index("--")
    args=command[cut+1:]
    require(args[:3]==["/usr/bin/timeout","--kill-after=5",str(gamma["limits"]["timeout_seconds"])] and
            args[3].endswith("/third_party/deagle-baseline/src/cbmc/deagle_exe") and
            args[4:]==s["command"][1:]==[*gamma["source_argv"],*gamma["verification_output"],"harness.c"] and
            "MemoryMax="+str(gamma["limits"]["memory_bytes"]) in command,name+" full command")
    for role,folder,rc in (("online",pair/"candidate",s["candidate_exit"]),("baseline",base,baseline["exit_code"])):
        verdict,target=classify((folder/"result.json").read_bytes(),rc,phi)
        require(verdict==s["candidate"]==baseline["result"]==w["online"],name+" "+role+" property")
        if verdict["classification"]=="VIOLATION":
            witness=normalize(target,phi,gamma,s["inputs_sha256"],"result.json",version="candidate")
            require(witness==read(folder/"cex1.json"),name+" "+role+" witness")

    model=read(run/"model-check.json")
    for phase in ("goto","raw_ssa","sc_input","full_model"):
        a,b=(phase_digest(read(p/(phase+".json"))) for p in (pair/"candidate",run/"full-model"))
        require(a==b==model["phase_digests"][phase]["full"],name+"/"+phase)
    native=s["native"]
    visits=[{k:v[k] for k in ("thread","function","pc")} for v in read(run/"full-model/visits.json")]
    skipped=native["reused_prefix_symex_steps"]
    require(len(visits)==skipped+native["executed_symex_steps"],name+" dispatches")
    if native["checkpoint_used"]:
        require(read(pair/"old/native-stats.json")["executed_dispatches"][:skipped]+
                read(pair/"candidate/native-stats.json")["executed_dispatches"]==visits and
                read(pair/"candidate/fresh-solver.json")["pid"]==ready["checkpoint_pid"],name+" checkpoint replay")
    settings=read(pair/"theory-settings.json")
    p0,p1=read(pair/"old/manifest.json"),read(pair/"frontend/manifest.json")
    require((p0["version_sha256"],p1["version_sha256"])==(s["old_version"],s["candidate_version"]) and
            p0["version_sha256"]==frozen["old_version"] and p1["source_sha256"]["program.c"]==sha,name+" version identity")
    h0,r0=freeze(pair/"old",settings,p0)
    h1,r1=freeze(pair/"candidate",settings,p1)
    cache=read(pair/"old/lemma-cache.json")
    export=read(pair/"old/theory-export.json")
    raw=[json.loads(line) for line in (pair/"old/native-conflicts.jsonl").read_bytes().splitlines()]
    require(len(raw)==w["theory"]["exported"] and cache["context_sha256"]==digest(h0) and
            export["cache_sha256"]==digest(cache),name+" OC export")
    for lemma in cache["lemmas"]:
        item=raw[lemma["raw_index"]]
        require(lemma["clause"]==r0.decode_clause(item["clause_x"]) and check(h0,lemma["clause"],lemma["certificate"]),
                name+" old certificate")
    plan,checked=validate(h0,h1,cache,r1,p0["version_sha256"])
    require(len(plan)==w["theory"]["accepted"] and checked["validation_rejected"]+export["export_rejected"]==w["theory"]["rejected"],
            name+" candidate cache validation")
    rows=read(pair/"candidate/native-import.json")["rows"]
    for row in rows:
        item=next(i for i in checked["records"] if i.get("plan_index")==row["id"])
        lemma=next(l for l in cache["lemmas"] if l["clause_sha256"]==item["clause_sha256"])
        require(signed(r1,lemma["clause"])==row["candidate_literals"],name+" candidate CNF receipt")
    require(sum(r["effect"] in ("attached","enqueued","contradiction") for r in rows)==w["theory"]["imported"],name+" actual imports")
    require(summary["candidate_sha256"]==sha and summary["skipped"]==skipped and
            summary["imported"]==w["theory"]["imported"] and summary["candidate"]==s["candidate"]["classification"],name+" overview")
    print(run.name,s["candidate"]["classification"],"skipped",skipped,"imported",w["theory"]["imported"])


def verify_ai(run, replay, isolation):
    request=read(run/"request.json")
    model=read(run/"repair/model.json")
    w=read(run/"workflow.json")
    packet=make_packet(run/"snapshot"/w["case"],read(run/"repair/cex0.json"))
    require(packet==read(run/"repair/model-input.json")==read(EVIDENCE/"ai/model-input.json") and
            packet_sha(packet)==model["model_input_sha256"]==isolation["public_input_sha256"]==request["repair_input_sha256"] and
            len(wire_text(packet).encode())==model["model_input_bytes"]==isolation["public_input_bytes"],
            "Mini inputs differ from the locally verified public subset")
    require(model==read(EVIDENCE/"ai/model.json") and model["api_base"]=="https://api.deepseek.com" and
            model["exit_status"]=="Submitted" and model["protected_inputs_unchanged"] and
            model["system_prompt"]==SYSTEM and model["task_instructions"]==INSTRUCTIONS,"Mini controller record")
    calls=model["requests"]
    usage=w["repair_usage"]
    require(0<len(calls)==usage["api_calls"]<=model["max_model_calls"] and model["automatic_retries"]==0 and
            len({r["response_id"] for r in calls})==len(calls) and all(r["returned_model"]==model["model"] for r in calls) and
            all(usage[key]==sum(r[key] for r in calls) for key in ("input_tokens","output_tokens")),"Provider receipts")
    first=[{"role":"system","content":SYSTEM},{"role":"user","content":INSTRUCTIONS+wire_text(packet)}]
    require(calls[0]["roles"]==["system","user"] and calls[0]["wire_messages_sha256"]==packet_sha(first),
            "First provider-bound messages differ from the public prompt")
    for prev,current in zip(calls,calls[1:]):
        require(all(x["id"] in current["returned_tool_ids"] for x in prev["tool_calls"]) and
                (not prev["reasoning_present"] or current["prior_reasoning_exact"]),"Tool result round trip")
    require(all("arguments" not in t and len(t["arguments_sha256"])==64 for r in calls for t in r["tool_calls"]),
            "Unexpected raw tool arguments")
    operations=model["operations"]
    writes=[op["sha256"] for op in operations if op["operation"]=="write"]
    sha=w["candidate_sha256"]
    require(writes and writes[-1]==sha==model["candidate_sha256"]==file_sha(run/"repair/submitted.c") and
            operations[-1]["operation"]=="submit","Verified tool edit did not become P1")
    old_lines=packet["program.c"].splitlines()
    new_lines=(run/"repair/submitted.c").read_text(encoding="utf-8").splitlines()
    changed=[(i,line) for i,(before,line) in enumerate(zip(old_lines,new_lines),1) if before!=line]
    require(len(old_lines)==len(new_lines) and len(changed)==1,"Expected the observed one-line model edit")
    number,line=changed[0]
    action=json.dumps({"command":"submit-line "+str(number)+" '"+line+"'"})
    edits=[tool for r in calls for tool in r["tool_calls"] if tool["tool"]=="bash" and
           tool["arguments_sha256"]==hashlib.sha256(action.encode()).hexdigest() and tool["arguments_bytes"]==len(action.encode())]
    require(len(edits)==1,"Cannot bind the provider's tool arguments to the changed C line")
    events={e["event"]:e["utc"] for e in timeline(run)}
    require(events["repair_started"]<=model["started_utc"]<=calls[0]["started_utc"]<=calls[-1]["started_utc"]<=
            model["finished_utc"]<=events["single_candidate_sealed"],"Mini calls did not follow the current P0 trace")
    require(replay["candidate_sha256"]==sha and replay["run_id"]!=w["run_id"] and replay["repair_usage"]["api_calls"]==0,
            "Mini replay changed the candidate or regenerated a repair")


def main():
    acceptance=read(EVIDENCE/"acceptance.json")
    lock=read(ROOT/"configs/stage05.lock.json")
    controller=read(ROOT/"configs/stage06.lock.json")
    require(all(file_sha(ROOT/name)==sha for name,sha in controller["module_sha256"].items()),
            "Controller or audit code differs from the Stage 6 release")
    require(all(controller[key]==lock[key] for key in
                ("development_commit","baseline_commit","development_sha256","baseline_sha256")),"Native release lock")
    with tempfile.TemporaryDirectory() as tmp:
        base=Path(tmp)
        count=unpack(base)
        for name,summary in acceptance["runs"].items():
            verify_run(base/"verification"/name,summary,lock)
        live,replay=(read(base/"verification"/n/"workflow.json") for n in ("live-batch","replay-live"))
        require(live["candidate_sha256"]==replay["candidate_sha256"] and live["run_id"]!=replay["run_id"] and
                replay["repair_usage"]["api_calls"]==0,"Frozen replay differs")
        isolation=read(EVIDENCE/"ai/sandbox-check.json")
        require(isolation==read(base/"meta/sandbox-check.json") and isolation["provider_calls"]==0 and
                isolation["native_isolation_preflight"] and isolation["denied_private_or_composed_commands"]==7,
                "Native sandbox check")
        verify_ai(base/"verification/ai-single-edit",read(base/"verification/replay-ai/workflow.json"),isolation)
        failed=base/"first-attempt"
        prior=read(failed/"workflow.json")
        refused=read(failed/"repair/model.json")
        extra=acceptance["additional_repair_failure"]
        require(prior==read(EVIDENCE/"ai/first-attempt/workflow.json") and refused==read(EVIDENCE/"ai/first-attempt/model.json")
                and prior["status"]==extra["status"]=="REPAIR_FAILED" and not prior["baseline_started"] and
                not (failed/"frozen.json").exists() and prior["repair_usage"]==extra["usage"] and
                len(refused["requests"])==extra["usage"]["api_calls"] and refused["model_input_sha256"]==isolation["public_input_sha256"],
                "First paid attempt must remain visible with its cost and without a candidate")
        require(sum(row["repair_usage"]["api_calls"] for row in acceptance["runs"].values())+extra["usage"]["api_calls"]==acceptance["deepseek_api_calls"],
                "Provider call total")
        gates=read(EVIDENCE/"probes.json")
        for name,result in gates["actual_runs"].items():
            run=base/"gates"/name
            observed=read(run/"workflow.json")
            events=[x["event"] for x in timeline(run)]
            require(observed["status"]==result["status"] and not observed["baseline_started"] and
                    "independent_full_started" not in events and not (run/"frozen.json").exists(),name)
    print("Verified",count,"archived files, all target results, live/replay handoffs and failure gates.")


if __name__=="__main__":
    main()
