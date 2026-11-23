#!/usr/bin/env python3
"""Replay published Stage 5 evidence using the Python standard library."""
import gzip
import hashlib
import json
import re
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from incdeagle.adapters.deagle import classify
from incdeagle.model.identity import digest, file_sha, read
from incdeagle.model.repeat import phase_digest
from incdeagle.theory.cache import ORIGINS, SITE, validate
from incdeagle.theory.certificate import check
from incdeagle.theory.context import freeze
from scripts.stage5.diagnostics import probes

EVIDENCE = ROOT / "reports/evidence/stage-05"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unpack(destination):
    index = read(EVIDENCE / "archive.json")
    archive = EVIDENCE / "full-runs.tar.gz"
    require(archive.name==index["archive"] and archive.stat().st_size==index["bytes"] and
            file_sha(archive)==index["sha256"], "Archive differs from its published index")
    seen = set()
    with tarfile.open(archive, "r|gz") as members:
        for member in members:
            path = PurePosixPath(member.name)
            require(member.isfile() and member.name==path.as_posix() and not path.is_absolute()
                    and ".." not in path.parts and "\\" not in member.name and ":" not in member.name
                    and member.name not in seen and member.name in index["files"], member.name)
            content = members.extractfile(member).read()
            require(hashlib.sha256(content).hexdigest()==index["files"][member.name], member.name)
            dest = destination.joinpath(*path.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            seen.add(member.name)
    require(seen==set(index["files"]), "Missing archive members")
    return len(seen)


def actual_literals(registry, clause):
    values = {slot:raw for _,raw,slot in registry.by_key.values()}
    return [values[slot]^negative for slot,negative in registry.bind(clause)]


def check_case(base, name, lock, summary):
    trial = base / name
    pair = trial / "pair"
    old, new = pair/"old", pair/"candidate"
    session = read(pair/"session.json")
    case = read(trial/"acceptance.json")
    require(case==read(EVIDENCE/"cases"/(name+".json")), name + " acceptance")
    theory = read(pair/"theory-summary.json")
    require(theory==case["theory"], name+" counters")
    settings = read(pair/"theory-settings.json")
    require(settings["native"]==session["tool"] and session["tool"]["commit"]==lock["development_commit"]
            and session["tool"]["development_sha256"]==lock["development_sha256"],
            name+" binary")
    for src, expected in settings["implementation"].items():
        require(file_sha(ROOT/src)==expected, "Code differs from the recorded audit implementation: "+src)
    registries = []
    contexts = []
    for role, folder, manifest in (("old",old,old/"manifest.json"),("candidate",new,pair/"frontend/manifest.json")):
        h, registry = freeze(folder,settings,read(manifest))
        require(h==read(folder/"theory-context.json") and digest(h)==theory[role.replace("candidate","new")+"_context"],
                name+" "+role+" graph")
        contexts.append(h)
        registries.append(registry)
        independent = trial/"independent"/role
        reference = read(independent/"run.json")
        require(reference["deagle_sha256"]==lock["baseline_sha256"], name+" baseline binary")
        rr = reference["runs"]["verify"]
        phi = {"id":reference["target"],"source":reference["target_source"]}
        verdict,_ = classify(gzip.decompress((independent/rr["document"]).read_bytes()),rr["exit_code"],phi)
        online,target = classify((folder/"result.json").read_bytes(),session[role+"_exit"],phi)
        require(online==verdict==session[role] and case[role]==summary[role]==verdict["classification"]
                and len(target.get("trace",[]))==session[role+"_trace_steps"], name+" "+role+" property")
        fresh = read(folder/"fresh-solver.json")
        require(fresh==case["fresh_solvers"][role] and not any(fresh[k] for k in ("clauses","learnts","assignments","solves")),
                name+" existing solver state")
    require(case["fresh_solvers"]["old"]["pid"]!=case["fresh_solvers"]["candidate"]["pid"], name+" fresh PIDs")
    for phase in ("goto","raw_ssa","sc_input","full_model"):
        online = phase_digest(read(new/(phase+".json")))
        full = phase_digest(read(trial/"full"/(phase+".json")))
        require(online==full==case["phase_digests"][phase]["full"], name+" "+phase)
    raw = [json.loads(line) for line in (old/"native-conflicts.jsonl").read_text().splitlines()]
    export, cache = read(old/"theory-export.json"), read(old/"lemma-cache.json")
    native_cycles = re.findall(rb"(\d+) cycles included\.",(old/"diagnostic.stdout").read_bytes())
    require(digest(cache)==export["cache_sha256"] and len(raw)==int(native_cycles[-1])==theory["exported"],name+" origin")
    origin = read(old/"manifest.json")["version_sha256"]
    for lemma in cache["lemmas"]:
        record = raw[lemma["raw_index"]]
        require(record["site"]==lemma["export_site"]==SITE and record["origin"]==lemma["origin"] in ORIGINS
                and lemma["kind"]=="oc-cycle" and lemma["origin_version"]==origin
                and lemma["clause"]==registries[0].decode_clause(record["clause_x"])
                and digest(lemma["clause"])==lemma["clause_sha256"]
                and check(contexts[0],lemma["clause"],lemma["certificate"]), name+" original raw clause")
    plan, audit = validate(*contexts,cache,registries[1],origin)
    candidate_audit = read(new/"theory-validation.json")
    require(audit["records"]==candidate_audit["records"] and audit["context_differences"]==theory["context_differences"],
            name+" candidate replay")
    native_plan = read(new/"native-plan.json")
    require(native_plan["valid_plan"] and native_plan["planned"]==len(plan)==theory["accepted"], name+" candidate plan")
    receipt = read(new/"native-import.json")
    require(receipt["rows"]==theory["native_rows"] and "lcnf" in receipt["api"], name+" native receipt")
    require(len(receipt["rows"])==len(case["checked_native_imports"]), name+" submitted rows")
    by_hash = {lemma["clause_sha256"]:lemma for lemma in cache["lemmas"]}
    by_plan = {r["plan_index"]:r["clause_sha256"] for r in audit["records"] if r["status"]=="accepted"}
    for row, recorded in zip(receipt["rows"],case["checked_native_imports"]):
        lemma = by_hash[by_plan[row["id"]]]
        require(recorded["old_debug_x"]==actual_literals(registries[0],lemma["clause"]) and
                recorded["candidate_debug_x"]==row["candidate_literals"]==actual_literals(registries[1],lemma["clause"]),
                name+" signed rebinding")
        if row["effect"]=="attached":
            require(row["clauses_after"]>row["clauses_before"], name+" clause table")
        elif row["effect"]=="enqueued":
            require(row["assignments_after"]>row["assignments_before"], name+" root propagation")
    imported = sum(r["effect"] in ("attached","enqueued","contradiction") for r in receipt["rows"])
    submitted = sum(r["effect"]!="already_inconsistent" for r in receipt["rows"])
    rejected = export["export_rejected"]+audit["validation_rejected"]
    expected_import = int(name in ("batch_total","batch_retained_error"))
    require(imported==expected_import==theory["imported"] and rejected==theory["rejected"]
            and submitted==theory["submitted"] and submitted-imported==theory["no_effect"]
            and len(plan)-submitted==theory["not_submitted"]
            and len(raw)==export["export_rejected"]+theory["supported"]
            and theory["supported"]==len(cache["lemmas"])+theory["deduplicated"]
            and theory["exported"]==theory["accepted"]+rejected+theory["deduplicated"],name+" counts")
    require(all(summary["lemmas"][k]==theory[k] for k in summary["lemmas"]),name+" published counters")
    if name=="batch_total":
        require(case["checked_native_imports"][0]["cnf_numbers_differ"],"The real CNF renumbering was not observed")
    print(f"{name}: {len(raw)} exported, {rejected} rejected, {imported} imported; {case['candidate']}")


def main():
    lock = read(ROOT/"configs/stage05.lock.json")
    for key, filename in (("bundle_sha256","deagle-stage05.bundle"),("patch_sha256","deagle-stage05-theory.patch")):
        require(file_sha(ROOT/"patches"/filename)==lock[key],filename)
    cases = read(EVIDENCE/"acceptance.json")["cases"]
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        count = unpack(root)
        for name, case in cases.items():
            check_case(root/"verification", name, lock, case)
        reproduced = probes(root/"verification/batch_total",root/"order-check.json")
        require(reproduced==read(EVIDENCE/"diagnostics.json"),"Independent order enumeration or guard probes differ")
    print(f"Verified {count} archived files, both property results for each pair, and the independent order enumeration.")


if __name__=="__main__":
    main()
