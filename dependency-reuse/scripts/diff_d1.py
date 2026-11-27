"""Produce an auditable D1 delta from two complete, single-query native manifests."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

from d1_identity import Keys, Model
from d1_theory import declarations


def jsonline(file, obj):
    file.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def one_var_table(path, models):
    translation = [{}, {}]
    by_role = [defaultdict(Counter), defaultdict(Counter)]
    reasons = [Counter(), Counter()]
    roles_blocked = [defaultdict(Counter), defaultdict(Counter)]
    examples = [defaultdict(list), defaultdict(list)]
    with path.open() as file:
        for line in file:
            side, v, peer, role, reason, anchor = line.rstrip().split("\t")
            side, v, peer = int(side), int(v), int(peer)
            state = "matched" if peer >= 0 else "unknown"
            by_role[side][role][state] += 1
            bucket = reason.partition(":")[0]
            reasons[side][bucket] += 1
            roles_blocked[side][role][bucket] += 1
            if len(examples[side][bucket]) < 3:
                examples[side][bucket].append([v, peer, reason, role, int(anchor)])
            if peer >= 0:
                translation[side][v] = 2*v if not side else peer
    assert len(translation[0]) == len(translation[1])
    return translation, dict(exclusive_roles=by_role, reasons=reasons, reasons_by_role=roles_blocked,
                             examples=examples, matched=len(translation[0]),
                             totals=[sum(c.total() for c in r.values()) for r in by_role],
                             constant_aliases=[{role:len(s) for role,s in m.folded.items()} for m in models])


def compare_theory(models, maps, out):
    lists = [declarations(m, t) for m,t in zip(models,maps)]
    known = [{(kind, key) for kind, _, _, key, _ in items if key} for items in lists]
    unproven = [{(kind, slot) for kind, _, slot, key, _ in items if not key and slot} for items in lists]
    guard_forms = []
    for items in lists:
        forms = {}
        for kind, local, slot, _, _ in items:
            if kind == "GuardBinding" and slot:
                raw = int(local[1])
                forms[slot] = raw if raw in (-2,-1) else "variable"
        guard_forms.append(forms)
    counts, unique, reasons = (defaultdict(Counter) for _ in range(3))
    examples = defaultdict(lambda: defaultdict(list))
    with gzip.open(out/"declarations.jsonl.gz", "wt") as file:
        for side in (0,1):
            seen = set()
            for kind, local, slot, key, why in lists[side]:
                changed_form = (kind == "GuardBinding" and slot in guard_forms[0] and slot in guard_forms[1]
                                and guard_forms[0][slot] != guard_forms[1][slot])
                if changed_form:
                    state, why = ("added" if side else "retired"), "guard_literal_form_changed"
                elif not key:
                    state = "unknown"
                elif (kind, key) in known[1-side]:
                    state = "matched"
                elif slot and (kind, slot) in unproven[1-side]:
                    state, why = "unknown", "peer_declaration_incomplete"
                else:
                    state = "retired" if not side else "added"
                label = f"P{side}_{state}"
                counts[kind][label] += 1
                if key and (kind, key) not in seen:
                    unique[kind][label] += 1
                    seen.add((kind, key))
                if why:
                    reasons[kind][f"P{side}/{why}"] += 1
                record = [side,kind,local,slot,key,state,why]
                jsonline(file,record)
                if len(examples[kind][label]) < 2:
                    examples[kind][label].append(record)
    return dict(occurrences=counts, distinct_resolved_keys=unique, reasons=reasons, examples=examples)


def compare_clauses(out):
    counts, distinct, reasons = (defaultdict(Counter) for _ in range(3))
    examples = defaultdict(lambda: defaultdict(list))
    statuses = {}
    with (out/"clause-counts.tsv").open() as file:
        for line in file:
            leaf, scope, a, b = line.split()
            a,b = int(a), int(b)
            statuses[int(leaf)] = (bool(a), bool(b))
            for side, n, peer in ((0,a,b),(1,b,a)):
                if not n: continue
                state = "matched" if peer else ("added" if side else "retired")
                label = f"P{side}_{state}"
                counts[scope][label] += n
                distinct[scope][label] += 1
    with (out/"occurrences.tsv").open() as file:
        for line in file:
            side,seq,scope,leaf,why = line.split()
            side,leaf = int(side),int(leaf)
            if not leaf:
                counts[scope][f"P{side}_unknown"] += 1
                reasons[scope][f"P{side}/" + why.partition(":")[0]] += 1
                state = "unknown"
            else:
                state = "matched" if statuses[leaf][1-side] else ("added" if side else "retired")
            bucket = examples[scope][f"P{side}_{state}"]
            if len(bucket) < 3: bucket.append([int(seq),leaf,why])
    return dict(occurrences=counts, distinct_resolved_keys=distinct, reasons=reasons, examples=examples)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("old","new","boolean_diff","new_directory"):
        parser.add_argument(arg,type=Path)
    parser.add_argument("--d3-mapping",action="store_true",help="use native aggregate layouts and certified duplicate gate contexts")
    args = parser.parse_args()
    out, engine = args.new_directory.resolve(),args.boolean_diff.resolve()
    out.mkdir(parents=True,exist_ok=False)
    start = time.monotonic()
    keys = Keys()
    paths = [args.old.resolve(),args.new.resolve()]
    models = [Model(p,keys,args.d3_mapping) for p in paths]
    anchors = [out/f"P{s}.anchors" for s in (0,1)]
    for s in (0,1): models[s].write_anchors(models[1-s],anchors[s])
    with gzip.open(out/"aliases.jsonl.gz","wt") as file:
        for side,m in enumerate(models):
            for key, lits in sorted(m.alias_lits.items()):
                jsonline(file,[side,key,sorted(lits)])
    subprocess.run([engine,*paths,*anchors,out, *(["--d3-mapping"] if args.d3_mapping else [])],check=True)
    maps, variables = one_var_table(out/"variables.tsv",models)
    clauses = compare_clauses(out)
    theory = compare_theory(models,maps,out)
    keys.save(out/"semantic-keys.jsonl.gz")
    compact_start = time.monotonic()
    for path in list(out.glob("*.tsv")) + anchors:
        with path.open("rb") as src, gzip.open(str(path)+".gz","wb",compresslevel=5) as dest:
            shutil.copyfileobj(src,dest,1<<20)
        path.unlink()
    result = dict(schema="D1-pair-v1", native_sha256=[digest(p) for p in paths],
                  engine_sha256=digest(engine), scope="one completed native SC Closure query per version",
                  targets=[m.rows["TARGET"] for m in models], assumptions=[m.rows["N"][0][1:] for m in models],
                  variables=variables, clauses=clauses, theory=theory,
                  analysis_wall_s=compact_start-start, evidence_compression_and_digest_wall_s=time.monotonic()-compact_start)
    (out/"summary.json").write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    print(out, variables["matched"], dict(clauses["occurrences"].get("B",{})),flush=True)


if __name__ == "__main__":
    main()
