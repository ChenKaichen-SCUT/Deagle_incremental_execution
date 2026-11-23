#!/usr/bin/env python3
"""Offline checks of binding guards and an independent SC order enumeration for batch_total."""
import argparse
import copy
import json
import shutil
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from incdeagle.model.identity import digest, read, save
from incdeagle.theory.cache import collect, validate
from incdeagle.theory.context import Registry, freeze


def require(x, message):
    if not x:
        raise ValueError(message)


def order_check(context, clause):
    """Enumerate schedules of a relaxation, with no CNF, data, property or Closure code.

    Only forced RF/guards and static PO/APO are enforced. Even atomic
    non-interleaving is relaxed. Failure to find any order proves the clause.
    """
    def key(a):
        return tuple(sorted(a.items()))
    decl = {key(x["atom"]):x["binding"] for x in context["atom_bindings"]}
    assumptions = {}
    for l in clause:
        b = decl[key(l["atom"])]
        assumptions[key(b["representative"])] = l["negative"] != b["opposite"]
    def enabled(atom):
        b = decl[key(atom)]
        if "constant" in b:
            return b["constant"]
        value = assumptions.get(key(b["representative"]))
        return value is not None and value != b["opposite"]

    names = sorted({v for edge in context["edges"] for v in (edge["from"],edge["to"])})
    index = {n:i for i,n in enumerate(names)}
    incoming = [0]*len(names)
    selected = {}
    guarded = set()
    for item in context["atom_bindings"]:
        atom = item["atom"]
        if atom["kind"] == "guard" and enabled(atom):
            guarded.add(atom["event"])
    for edge in context["edges"]:
        a,b = edge["from"],edge["to"]
        if edge["kind"] == "rf":
            if not enabled({"kind":"rf","write":a,"read":b}):
                continue
            selected.setdefault(b,[]).append(a)
        incoming[index[b]] |= 1 << index[a]
    addresses = sorted({context["events"][w]["solver_address"] for ws in selected.values() for w in ws})
    last_slot = {a:i for i,a in enumerate(addresses)}
    changed = {index[n]:last_slot[context["events"][n]["solver_address"]] for n in guarded
               if n in index and context["events"][n]["solver_address"] in last_slot}
    read_from = {index[r]:[(last_slot[context["events"][w]["solver_address"]], index[w]) for w in ws if w in guarded]
                 for r,ws in selected.items()}
    complete = (1 << len(names)) - 1
    states = 0
    @lru_cache(None)
    def extend(mask, last):
        nonlocal states
        states += 1
        if states > 250000:
            raise ValueError("Independent order-check budget reached")
        if mask == complete:
            return True
        for i, need in enumerate(incoming):
            if mask & (1<<i) or need & ~mask:
                continue
            if any(last[a]!=wanted for a,wanted in read_from.get(i,())):
                continue
            now = last
            if i in changed:
                temp = list(last)
                temp[changed[i]] = i
                now = tuple(temp)
            if extend(mask | (1<<i), now):
                return True
        return False
    exists = extend(0,tuple(-1 for _ in addresses))
    return {"has_schedule":exists, "states_visited":states,"graph_nodes":len(names),
            "constraints":"PO, APO as precedence, selected RF, forced write guards and last writer only"}


def probes(case_dir, output):
    pair = case_dir/"pair"
    old, current = pair/"old", pair/"candidate"
    h0 = read(old/"theory-context.json")
    settings = read(pair/"theory-settings.json")
    h1, reg = freeze(current, settings, read(pair/"frontend/manifest.json"))
    cache = read(old/"lemma-cache.json")
    origin = read(old/"manifest.json")["version_sha256"]
    require(h0==h1 and cache["lemmas"], "Probes require the genuine unchanged batch_total theory")
    first = cache["lemmas"][0]
    outcomes = {}
    for label, target, value in (
            ("schema", "schema", h1["schema"]+1), ("backend", "backend", "different backend"),
            ("engine", "engine", {"other":True}), ("static_edges", "edges", h1["edges"][:-1])):
        changed = dict(h1)
        changed[target] = value
        plan, r = validate(h0,changed,cache,reg,origin)
        require(not plan and r["validation_rejected"]==len(cache["lemmas"]), label)
        outcomes[label] = r["context_differences"]

    atom0 = {"kind":"guard","event":"a"}
    atom1 = {"kind":"guard","event":"b"}
    atom2 = {"kind":"rf","write":"w","read":"r"}
    def aliases(values):
        return Registry([(a,v,i) for i,(a,v) in enumerate(zip((atom0,atom1,atom2),values))])
    original = aliases((20,21,20))
    shifted = aliases((103,102,103))
    meaning = original.decode_clause([21])
    slot,neg = shifted.bind(meaning)[0]
    require(original.declarations==shifted.declarations and (103,102,103)[slot]^neg == 102,
            "Signed CNF renaming lost the original meaning")
    outcomes["signed_alias_and_global_polarity_flip"] = {
        "old":[20,21,20],"new":[103,102,103],"old_clause":[21],"new_clause":[102],"clause":meaning}
    for label,bindings in (("reverse_alias_changed",aliases((103,103,103))),
                           ("guard_constant_changed",aliases((-1,102,103)))):
        a,b = dict(h0,atom_bindings=original.declarations),dict(h1,atom_bindings=bindings.declarations)
        c = dict(cache,context_sha256=digest(a))
        plan,r = validate(a,b,c,bindings,origin)
        require(not plan and "context_changed:atom_bindings" in r["context_differences"],label)
        outcomes[label] = r["context_differences"]
    true_guard, false_guard = aliases((-1,20,21)), aliases((-2,20,21))
    a = dict(h0,atom_bindings=true_guard.declarations)
    b = dict(h1,atom_bindings=false_guard.declarations)
    plan, changed = validate(a,b,dict(cache,context_sha256=digest(a)),false_guard,origin)
    require(not plan and "context_changed:atom_bindings" in changed["context_differences"],"constant flip")
    outcomes["declared_true_to_false"] = changed["context_differences"]
    try:
        reg.decode_clause([])
    except ValueError as e:
        outcomes["empty_reason"] = str(e)
    else:
        raise ValueError("Unsourced empty conflict accepted")
    try:
        reg.decode_clause([2*(max(reg.by_var)+10)])
    except ValueError as e:
        outcomes["unmapped_dynamic_co"] = str(e)
    else:
        raise ValueError("Unmapped CO accepted")
    changes = {
        "mixed_cdcl_origin":lambda row:row.update(export_site="analyze"),
        "propagation_reason":lambda row:row.update(origin="propagation"),
        "unproved_clause":lambda row:row.update(certificate=[]),
        "bad_origin_version":lambda row:row.update(origin_version="stale"),
    }
    for label, change in changes.items():
        c = copy.deepcopy(cache)
        c["lemmas"] = [c["lemmas"][0]]
        change(c["lemmas"][0])
        plan,r = validate(h0,h1,c,reg,origin)
        require(not plan and r["validation_rejected"]==1,label)
        outcomes[label]=r["records"][0]["reason"]

    _, r0 = freeze(old,settings,read(old/"manifest.json"))
    raw = [json.loads(l) for l in (old/"native-conflicts.jsonl").read_text().splitlines()][first["raw_index"]]
    with tempfile.TemporaryDirectory() as temp:
        copy_old = Path(temp)/"old"
        copy_old.mkdir()
        save(copy_old.parent/"theory-settings.json",settings)
        for filename in ("full_model.json","goto.json","visits.json","native-bindings.json","harness.c","program.c"):
            shutil.copyfile(old/filename, copy_old/filename)
        (copy_old/"native-conflicts.jsonl").write_text((json.dumps(raw)+"\n")*2)
        collected = collect(copy_old,read(old/"manifest.json"))
        counts = {k:collected[k] for k in ("exported","supported","deduplicated","unique")}
        require(list(counts.values())==[2,2,1,1],"Replayed duplicate was not removed")
        outcomes["duplicated_raw_record_fixture"] = counts
    require(0 in raw["levels"] and len(first["clause"]) >= 2,"Expected real root-level premise")
    shortened = r0.decode_clause([x for x,level in zip(raw["clause_x"],raw["levels"]) if level!=0])
    c = copy.deepcopy(cache)
    c["lemmas"] = [dict(first,clause=shortened,clause_sha256=digest(shortened))]
    plan, r = validate(h0,h1,c,reg,origin)
    require(not plan and r["validation_rejected"]==1,"Retained a proof with a missing level-zero premise")
    outcomes["old_level_zero_premise_removed"] = r["records"][0]["reason"]
    independent = {"no_premises":order_check(h1,[]),"original_lemma_falsified":order_check(h1,first["clause"]),
                   "old_root_premise_removed":order_check(h1,shortened)}
    require(independent["no_premises"]["has_schedule"] and not independent["original_lemma_falsified"]["has_schedule"]
            and independent["old_root_premise_removed"]["has_schedule"],"Independent order test failed")
    result = {"origin":origin,"real_clause_sha256":first["clause_sha256"],"probes":outcomes,
              "independent_order_check":independent}
    save(output,result)
    return result


if __name__=="__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("case_dir",type=Path)
    cli.add_argument("--out",type=Path,required=True)
    args = cli.parse_args()
    print(json.dumps(probes(args.case_dir,args.out)["independent_order_check"],indent=2))
