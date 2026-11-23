"""Offline release audit using Python's standard library and Git."""
import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.adapters.deagle import classify
from incdeagle.counterexample import normalize
from incdeagle.model.identity import digest, file_sha, read
from incdeagle.theory.cache import validate
from incdeagle.theory.certificate import check
from incdeagle.theory.context import BACKEND, SCHEMA, freeze
from scripts.stage7.oracles import independent, retained_projection
from scripts.stage7.results import derive

EVIDENCE=ROOT/"reports/evidence/stage-07"


def need(value,reason):
    if not value:raise ValueError(reason)


def restore(evidence,dest):
    index=read(evidence/"archive.json")
    store=dest/"objects"
    store.mkdir()
    seen=set()
    for name,expected in index["archives"].items():
        path=evidence/name
        need(re.fullmatch(r"raw-\d+\.zip",name) and path.stat().st_size==expected["bytes"] and file_sha(path)==expected["sha256"],name)
        with zipfile.ZipFile(path) as zipped:
            for entry in zipped.infolist():
                sha=entry.filename[:-3]
                need(entry.filename==sha+".gz" and re.fullmatch("[a-f0-9]{64}",sha) and sha not in seen and
                     index["objects"].get(sha)==name,"Unexpected content object")
                data=gzip.decompress(zipped.read(entry))
                need(hashlib.sha256(data).hexdigest()==sha,"Content checksum "+sha)
                (store/sha).write_bytes(data)
                seen.add(sha)
    need(seen==set(index["objects"])==set(index["files"].values()),"Missing or unreferenced object")
    for name,sha in index["files"].items():
        p=PurePosixPath(name)
        need(p.as_posix()==name and not p.is_absolute() and ".." not in p.parts and "\\" not in name and ":" not in name and
             p.parts[0] in ("diagnostics","trials","sources","fixed-traces","matrix.json","plan.json","doctor.json"),name)
        path=dest.joinpath(*p.parts)
        path.parent.mkdir(parents=True,exist_ok=True)
        try:
            os.link(store/sha,path)
        except OSError:
            # Some filesystems or app sandboxes allow copies only.
            shutil.copyfile(store/sha,path)
    return len(index["files"])


def signed(registry,clause):
    by_slot={slot:raw for _,raw,slot in registry.by_key.values()}
    return [by_slot[slot]^sign for slot,sign in registry.bind(clause)]


def audit_theory(pair,hashes):
    old,new=pair/"old",pair/"candidate"
    first,second=read(old/"manifest.json"),read(pair/"frontend/manifest.json")
    need(first["source_sha256"]["program.c"]==hashes["old/program.c"] and
         second["source_sha256"]["program.c"]==hashes["candidate/program.c"],"Manifest source identities")
    settings=read(pair/"theory-settings.json")
    cache=read(old/"lemma-cache.json")
    exported=read(old/"theory-export.json")
    raw=[json.loads(x) for x in (old/"native-conflicts.jsonl").read_bytes().splitlines()]
    try:
        h0,r0=freeze(old,settings,first)
        need(exported["snapshot_error"] is None,"Unexpected recorded old-context refusal")
    except ValueError as exc:
        reason=str(exc)
        need(exported["snapshot_error"]==reason and not cache["lemmas"] and exported["unique"]==0
             and exported["export_rejected"]==len(raw) and len(exported["records"])==len(raw) and
             all(r["reason"]=="old_context_unavailable:"+reason and r["status"]=="rejected"
                 for r in exported["records"]),"Old context refusal not reproduced")
        h0={"schema":SCHEMA,"backend":BACKEND,"unavailable":reason}
        r0=None
    need(h0==read(old/"theory-context.json"),"Recorded old theory context")
    need(cache["context_sha256"]==digest(h0) and exported["cache_sha256"]==digest(cache),"OC cache origin")
    for lemma in cache["lemmas"]:
        need(lemma["clause"]==r0.decode_clause(raw[lemma["raw_index"]]["clause_x"]) and
             check(h0,lemma["clause"],lemma["certificate"]),"Bad OC certificate")
    try:
        h1,r1=freeze(new,settings,second)
    except ValueError as exc:
        refused=read(new/"theory-validation.json")
        need(refused["context_differences"]==[str(exc)] and refused["accepted"]==0 and
             refused["validation_rejected"]==exported["unique"] and read(new/"native-plan.json")["planned"]==0 and
             read(new/"native-import.json")["rows"]==[],"Candidate context refusal not reproduced")
        plan,checked=[],refused
        r1=None
    else:
        plan,checked=validate(h0,h1,cache,r1,first["version_sha256"])
    theory=read(pair/"theory-summary.json")
    need(theory["exported"]==len(raw) and theory["accepted"]==len(plan) and
         theory["rejected"]==exported["export_rejected"]+checked["validation_rejected"],"Theory audit disagrees")
    rows=read(new/"native-import.json")["rows"]
    for row in rows:
        item=next(r for r in checked["records"] if r.get("plan_index")==row["id"])
        lemma=next(l for l in cache["lemmas"] if l["clause_sha256"]==item["clause_sha256"])
        need(signed(r1,lemma["clause"])==row["candidate_literals"],"New signed CNF binding")
    need(theory["imported"]==sum(r["effect"] in ("attached","enqueued","contradiction") for r in rows),"Actual solver effects")


def check_verdict(folder,rc,phi,gamma,hashes,version,expected):
    result,target=classify((folder/"result.json").read_bytes(),rc,phi)
    need(result==expected,"Raw verifier output differs from the reported property")
    if result["classification"]!="VIOLATION":return None
    file=folder/("cex0.json" if version=="old" else "cex1.json")
    trace=read(file)
    regenerated=normalize(target,phi,gamma,hashes,"result.json",version=version)
    need(regenerated==trace,"Raw counterexample and normalized trace differ")
    return trace


def audit(root,rows):
    plan=read(root/"plan.json")
    matrix=read(root/"matrix.json")
    lock=read(ROOT/"configs/stage05.lock.json")
    need(len(rows)==plan["repetitions"]*len(plan["cases"]),"Incomplete matched experiment")
    for name,item in matrix.items():
        case=root/item["case_dir"]
        need(all(file_sha(case/path)==sha for path,sha in item["files"].items()),"Frozen source "+name)
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            (d/"program.c").write_bytes((case/"old/program.c").read_bytes())
            subprocess.run(["git","init","--quiet",str(d)],check=True)
            subprocess.run(["git","-C",str(d),"-c","core.autocrlf=false","apply",str(case/"patch.diff")],check=True)
            need(file_sha(d/"program.c")==item["files"]["candidate/program.c"],"Patch replay "+name)
        trace=read(root/"fixed-traces"/(name+".json"))
        need(trace["p0_sha256"]==item["files"]["old/program.c"] and trace["property"]==read(case/"phi.json")["id"],"Reference experiment trace")
    end=0
    per_case={}
    witness_count=0
    for r in rows:
        name=r["case_id"]
        t=root/"trials"/name/str(r["repeat"])
        item=matrix[name]
        c=root/item["case_dir"]
        phi,gamma=read(c/"phi.json"),read(c/"gamma.json")
        hashes=item["files"]
        expected=[*gamma["source_argv"],*gamma["verification_output"],"harness.c"]
        per_case.setdefault(name,[]).append(r["order"].index("full")<r["order"].index("incremental"))
        verdicts={}
        for phase in r["order"]:
            d=t/phase
            s=read(d/"service.json")
            need(end<=s["launch_ns"]<s["finish_ns"] and s["memory_max"]==gamma["limits"]["memory_bytes"] and
                 s["timeout_seconds"]==gamma["limits"]["timeout_seconds"],"Overlapping services or different limits")
            end=s["finish_ns"]
            m=read(d/"measurement.json")
            if m["status"]!="COMPLETED":continue
            verdicts[phase]=m["verdict"]
            if phase!="incremental":
                version="old" if phase=="old_full" else "candidate"
                need(m["command"][4:]==expected and m["binary_sha256"]==lock["baseline_sha256"],"Baseline selection")
                trace=check_verdict(d/"verify",m["exit_code"],phi,gamma,m["inputs"],version,m["verdict"])
            else:
                pair=d/"pair"
                sess=read(pair/"session.json")
                verdicts["old_instrumented"]=sess["old"]
                need(m["native"]==sess["native"] and m["theory"]==read(pair/"theory-summary.json"),"Unbound native counters")
                need(sess["command"][1:]==expected and sess["tool"]["development_sha256"]==lock["development_sha256"] and
                     sess["tool"]["commit"]==lock["development_commit"],"Incremental selection")
                old_hash={"program.c":hashes["old/program.c"],"harness.c":hashes["harness.c"]}
                check_verdict(pair/"old",sess["old_exit"],phi,gamma,old_hash,"old",sess["old"])
                trace=check_verdict(pair/"candidate",sess["candidate_exit"],phi,gamma,m["inputs"],"candidate",m["verdict"])
                audit_theory(pair,hashes)
                full_visits=read(root/"diagnostics"/name/"full-model/visits.json")
                if sess["native"]["checkpoint_used"]:
                    head=read(pair/"old/native-stats.json")["executed_dispatches"][:r["reused_prefix_steps"]]
                    tail=read(pair/"candidate/native-stats.json")["executed_dispatches"]
                    need(head+tail==[{k:v[k] for k in ("thread","function","pc")} for v in full_visits],"Native prefix/suffix dispatch order")
                else:
                    need(r["reused_prefix_steps"]==0 and bool(r["fallback_reason"]),"Unexplained fallback")
            if phase!="old_full" and trace and name in ("batch_retained","partial_counter"):
                need(retained_projection(name,trace),"Counterexample projection outside source action orders")
                witness_count+=1
        if r["agreement_status"]=="DEFINITE_AGREEMENT":
            need(verdicts["full"]==verdicts["incremental"] and verdicts["old_full"]==verdicts["old_instrumented"]
                 and verdicts["old_full"]["classification"]=="VIOLATION","Different target results or ineligible old source")
        need(r["api_calls"]==0 and not (t/"incremental/repair/model.json").exists(),"Unexpected repair API activity")
    for orders in per_case.values():
        need(all(a!=b for a,b in zip(orders,orders[1:])),"Case order did not alternate")
    return witness_count


def build_and_probe(evidence,root):
    build=read(evidence/"build-receipt.json")
    native=read(ROOT/"configs/stage05.lock.json")
    need(build["exit"]==0 and build["initial_verifier_binaries"]==0 and build["all_locked"] and
         build["build_entry_sha256"]==file_sha(ROOT/"scripts/stage7/build.sh") and
         build["log_gzip_sha256"]==file_sha(evidence/"build.log.gz") and
         all(build["binaries"][k]["sha256"]==native[k+"_sha256"] and build["binaries"][k]["commit"]==native[k+"_commit"]
             for k in ("development","baseline")),"Clean build receipt")
    m=read(root/"matrix.json")["airline_reservations_6"]
    phi=read(root/m["case_dir"]/"phi.json")
    probe=read(evidence/"old-solver-probe.json")
    with tarfile.open(evidence/"old-solver-probe.tar.gz","r:gz") as archive:
        for name,r in probe.items():
            def raw(file):
                return archive.extractfile(name+"/"+file).read()
            cmd=json.loads(raw("command.json"))
            result,target=classify(raw("result.json"),cmd["exit_code"],phi)
            messages=json.loads(raw("result.json"))
            solver_times=[float(v["messageText"].split(": ")[1][:-1]) for v in messages
                          if v.get("messageText","").startswith("Runtime Solver: ")]
            need(result==r["result"] and r["steps"]==len(target["trace"]) and solver_times==[r["runtime"]["Solver"]] and
                 hashlib.sha256(raw("program.c")).hexdigest()==r["source_sha256"]==m["files"]["old/program.c"] and
                 hashlib.sha256(raw("harness.c")).hexdigest()==m["files"]["harness.c"] and not r["old_cache_collection"] and
                 r["binary_sha256"]==native[("baseline" if name=="baseline" else "development")+"_sha256"],"Old solver control")


def main(evidence):
    lock=read(ROOT/"configs/stage07.lock.json")
    need(all(file_sha(ROOT/p)==h for p,h in lock["files_sha256"].items()),"Stage 7 sources or fixtures changed")
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        count=restore(evidence,root)
        rows,summary=derive(root)
        need(rows==read(evidence/"measurements.json") and summary==read(evidence/"summary.json"),"Published aggregates differ")
        need(independent()==read(evidence/"schedule-oracles.json"),"Independent schedule enumerations")
        proofs=audit(root,rows)
        build_and_probe(evidence,root)
        print("Verified",count,"native files,",len(rows),"matched trials,",summary["totals"]["distinct_pairs"],
              "frozen cases and",proofs,"retained-error witness projections.")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evidence",type=Path,default=EVIDENCE)
    main(p.parse_args().evidence)
