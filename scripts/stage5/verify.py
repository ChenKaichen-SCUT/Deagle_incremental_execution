#!/usr/bin/env python3
"""Verify model equality, the independent property result and each actual native import."""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from incdeagle.model.identity import read, save
from incdeagle.theory.cache import validate
from incdeagle.theory.context import freeze
from scripts.stage4.verify import verify as verify_model, require
from scripts.stage5.session import CASES, TheorySession


def verify(name, out, *, batch_error_probe=False):
    result = verify_model(name, out, batch_error_probe=batch_error_probe,
                          session_script=ROOT/"scripts/stage5/session.py", binary=TheorySession.binary)
    pair = out/"pair"
    summary = read(pair/"theory-summary.json")
    export = read(pair/"old/theory-export.json")
    fresh = {v:read(pair/v/"fresh-solver.json") for v in ("old","candidate")}
    for state in fresh.values():
        require(all(state[field] == 0 for field in ("clauses","learnts","assignments","solves")),
                "Solver factory did not produce an empty solver")
    require(fresh["old"]["pid"] != fresh["candidate"]["pid"], "Old and candidate process isolation failed")
    counter = (pair/"old/diagnostic.stdout").read_text()
    cycles = re.findall(r"(\d+) cycles included\.", counter)
    require(bool(cycles) and int(cycles[-1])==summary["exported"], "Raw hook and native cycle count differ")
    require(export["snapshot_error"] is None, "Old graph could not be audited")
    native_plan = read(pair/"candidate/native-plan.json")
    require(native_plan["valid_plan"] and native_plan["planned"]==summary["accepted"],
            "The native backend did not validate and receive the audited plan")
    settings = read(pair/"theory-settings.json")
    old_manifest = read(pair/"old/manifest.json")
    h0, r0 = freeze(pair/"old", settings, old_manifest)
    h1, r1 = freeze(pair/"candidate", settings, read(pair/"frontend/manifest.json"))
    cache = read(pair/"old/lemma-cache.json")
    plan, checked = validate(h0,h1,cache,r1,old_manifest["version_sha256"])
    require(len(plan)==summary["accepted"], "Cannot replay the accepted bindings")
    checks = []
    for row in summary["native_rows"]:
        item = next(x for x in checked["records"] if x.get("plan_index")==row["id"])
        lemma = next(l for l in cache["lemmas"] if l["clause_sha256"]==item["clause_sha256"])
        def actual(registry):
            by_slot = {slot:x for _,x,slot in registry.by_key.values()}
            return [by_slot[s]^opp for s,opp in registry.bind(lemma["clause"])]
        old_literals, new_literals = actual(r0), actual(r1)
        require(row["candidate_literals"]==new_literals, "New solver received incorrect literals")
        checks.append({"clause_sha256":lemma["clause_sha256"],"kind":lemma["kind"],
                       "semantic_clause":lemma["clause"],"proof_rules":[r["rule"] for r in lemma["certificate"]],
                       "old_debug_x":old_literals,"candidate_debug_x":new_literals,
                       "cnf_numbers_differ":[x//2 for x in old_literals]!=[x//2 for x in new_literals],
                       "effect":row["effect"],"clauses_before":row["clauses_before"],"clauses_after":row["clauses_after"]})
    result["theory"] = summary
    result["fresh_solvers"] = fresh
    result["checked_native_imports"] = checks
    save(out/"acceptance.json",result)
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("case",choices=sorted(CASES))
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--batch-error-probe",action="store_true")
    args=p.parse_args()
    r=verify(args.case,args.out.resolve(),batch_error_probe=args.batch_error_probe)
    print(r["case"],r["candidate"],"old exported",r["theory"]["exported"],"actually imported",r["theory"]["imported"])
