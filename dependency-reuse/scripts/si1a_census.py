"""SI-1A read-only census. All joins to an atom or a cache entry are within one frozen model."""
import argparse
from array import array
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
from pathlib import Path

from cases42 import load
from compact43 import DenseLibrary, RULES
from d43_owner_probe import canonical_site
from run_stock import BASE, save, sha


def check(ok, reason):
    if not ok:
        raise ValueError(reason)


def rows(path):
    with path.open() as f:
        yield from csv.DictReader(f, delimiter="\t")


def fields(path):
    with path.open() as f:
        for line in f:
            yield line.rstrip("\n").split("\t")


def fingerprint(path, cwd):
    """All rows up to and including the first N. Only unordered hints and intern handles are normalized."""
    digest = hashlib.sha256()
    terms, hints, counts = {}, [], Counter()
    streams = {key: hashlib.sha256() for key in (b"C", b"A", b"G", b"EDGE", b"GUARD", b"NODE", b"N")}
    with path.open("rb") as f:
        for line in f:
            tag, *parts = line.rstrip(b"\n").split(b"\t")
            counts[tag.decode()] += 1
            if tag in streams:
                streams[tag].update(line)
            if tag == b"TERM":
                i, op, typ, value, *kids = parts
                check(i not in terms, "duplicate TERM")
                terms[i] = hashlib.sha256(b"\t".join([op, typ, value, *(terms[k] for k in kids)])).hexdigest().encode()
            elif tag in (b"H", b"VALUE_DEF"):
                name, idx = parts
                hint = tag + b"\t" + name + b"\t" + terms[idx] + b"\n"
                if tag == b"H":
                    hints.append(hint)
                else:
                    digest.update(hint)
            elif tag == b"SITE41":
                i, value = parts
                digest.update(b"SITE41\t" + i + b"\t" + canonical_site(value, cwd.encode()) + b"\n")
            else:
                digest.update(line)
            if tag == b"N":
                break
    check(counts["N"] == 1, "first query boundary missing")
    for item in sorted(hints) + sorted(terms.values()):
        digest.update(item)
    return dict(canonical_sha256=digest.hexdigest(), rows=dict(sorted(counts.items())),
                ordered_stream_sha256={k.decode(): h.hexdigest() for k,h in streams.items()})


def trace_data(path):
    ownership = [None]  # zero is reserved
    cache, cross, types = {}, set(), {}
    events, observed_types = Counter(), Counter()
    with gzip.open(path, "rt") as f:
        for line in f:
            tag, *v = line.rstrip("\n").split("\t")
            if tag == "R":
                lo, width = map(int, v[:2])
                check(lo == len(ownership), "non-contiguous SAT allocation")
                site, op = v[2:4]
                ownership.extend([(site, op)] * width)
            elif tag in ("H", "M"):
                domain, entry, lo, hi, op, phase, ctx = v
                k = (domain, entry)
                events[f"{domain}_{tag}"] += 1
                if tag == "M":
                    check(k not in cache, "reused live cache handle")
                    cache[k] = (int(lo), int(hi), phase, int(ctx))
                else:
                    first, last, p, c = cache[k]
                    if int(ctx) >= 0 and c >= 0 and (p, c) != (phase, int(ctx)):
                        events[f"{domain}_other_owner_hits"] += 1
                        if last > first:
                            cross.add((first, last))
            elif tag == "Y":
                name, kind, width = v
                check(name not in types, "duplicate native BV symbol")
                types[name] = kind
                observed_types[kind] += 1
            elif tag == "N":
                check(int(v[0]) == len(ownership), "wrong final SAT range")
                events["boundaries"] += 1
            else:
                raise ValueError(tag)
    check(events["boundaries"] == 1, "missing observer boundary")
    diff = array("i", [0]) * (len(ownership) + 1)
    for first, last in cross:
        diff[first] += 1
        diff[last] -= 1
    depth, touched = 0, set()
    for i, delta in enumerate(diff):
        depth += delta
        if depth:
            touched.add(i)
    return ownership, types, observed_types, events, touched


def local_escape(s):
    return "".join("%" + format(ord(c), "02x") if c == "%" or ord(c) < 32 or ord(c) == 127 else c for c in s)


def kind(site, op):
    filename, _, n = site.rpartition(":")
    if filename.endswith("/cnf.cpp"):
        return "cnf_gate"
    if filename.endswith("/bv_utils.cpp"):
        return "bv_helper"
    if filename.endswith("/equality.cpp"):
        return "equality_helper"
    if filename.endswith("/boolbv_index.cpp") and n in ("68", "220", "369"):
        return "fresh_free_index"
    if site.endswith(("boolbv.cpp:89", "prop_conv_solver.cpp:220", "prop_conv_solver.cpp:319",
                      "boolbv_union.cpp:33", "boolbv_extractbit.cpp:31")):
        return "fresh_free_other"
    if site.endswith("boolbv_map.cpp:59"):
        return "named_bv_allocation"
    if site.endswith("prop_conv_solver.cpp:70"):
        return "named_bool_allocation"
    return "other_allocation"


CATEGORIES = ("RF", "Guard", "pointer_aggregate", "ssa_bit", "ordinary_bool", "fresh_free", "auxiliary", "unknown")


def scan(case, side, model, trace, lib, mu, pre, exact):
    allocation, types, type_counts, cache, revisited = trace_data(trace)
    types = {local_escape(k): v for k, v in types.items()}
    n = len(allocation)
    check(set(mu) == set(range(1, n)) == set(pre), f"incomplete map range {case} {side}")
    # A port and its allocation site can describe different things when equality aliases fired.
    flags = defaultdict(set)
    gate, source_names, layout_names = Counter(), set(), set()
    value_type = Counter()
    usedb, usedt, conclusion = set(), set(), set()
    names_per_var = Counter()
    port_constants, signed_ports = Counter(), Counter()
    sizes = Counter()
    chains = {}
    defs = defaultdict(list)
    all_b = {} if side == "P1" else None
    occurrence = 0
    for row in fields(model):
        tag, v = row[0], row[1:]
        if tag == "V":
            source_names.add(v[0])
        elif tag == "A_LAYOUT":
            layout_names.add(v[0])
        elif tag == "C":
            literal = tuple(map(int, v[1:]))
            occurrence += 1
            if v[0] == "B":
                sizes["permanent_C"] += 1
                sizes["permanent_C_literals"] += len(literal)
                if all_b is not None:
                    all_b.setdefault(tuple(sorted(set(literal))), occurrence)
            if lib and lib.observed(0, occurrence - 1):
                check(v[0] == "B", "non-permanent UsedLeaf")
                usedb.update(x // 2 for x in literal if x >= 2)
                sizes["used_C"] += 1
                sizes["used_C_literals"] += len(literal)
        elif tag == "A":
            name, encoded_type, _, raw = v
            lit = int(raw)
            typ = types.get(name, encoded_type)
            value_type[typ] += 1
            if lit < 2:
                port_constants[typ] += 1
                continue
            var = lit // 2
            signed_ports["negative" if lit & 1 else "positive"] += 1
            names_per_var[var] += 1
            if typ in ("pointer", "struct", "struct_tag", "union", "union_tag", "array", "vector"):
                flags["pointer_aggregate"].add(var)
                flags["type_" + typ].add(var)
            elif typ == "bool":
                flags["ordinary_bool"].add(var)
            elif name in source_names and typ:
                flags["ssa_bit"].add(var)
            else:
                flags["other_named"].add(var)
            if name in source_names:
                flags["has_V"].add(var)
            if name in layout_names:
                flags["A_LAYOUT"].add(var)
        elif tag == "G":
            op, result, *args = v
            lit = int(result)
            gate[op] += 1
            if lit >= 2:
                flags["native_gate_result"].add(lit // 2)
                defs[lit // 2].append((op, lit, list(map(int, args))))
                if lit & 1:
                    sizes["negative_G_output_rows"] += 1
        elif tag == "EDGE" and v[0].lower() == "rf":
            lit = int(v[3])
            if lit >= 2:
                flags["RF"].add(lit // 2)
            sizes["rf_port_rows"] += 1
        elif tag == "GUARD":
            lit = int(v[1])
            if lit >= 2:
                flags["Guard"].add(lit // 2)
            sizes["guard_port_rows"] += 1
        elif tag == "N":
            check(int(v[0]) == n, "observed N mismatch")
            break
    for var in range(1, n):
        k = kind(*allocation[var])
        if k.startswith("fresh_free"):
            flags["fresh_free"].add(var)
        if k in ("cnf_gate", "bv_helper", "equality_helper") or var in flags["native_gate_result"]:
            flags["auxiliary"].add(var)
        if k == "named_bool_allocation":
            flags["ordinary_bool"].add(var)
    flags["multiple_named_ports"] = {v for v, count in names_per_var.items() if count > 1}
    flags["multiple_G_rows"] = {v for v, d in defs.items() if len(d) > 1}
    flags["later_cache_hit_other_owner_interval"] = revisited
    allvars = set(range(1, n))
    missing = {v for v, x in mu.items() if x < 0}
    semantic = {v for v, x in pre.items() if x[0] >= 2}
    check(all(mu[v] == pre[v][0] for v in semantic), "semantic binding changed in final map")
    scopes = {"all": allvars, "final_unmapped": missing, "semantic_mapped": semantic,
              "structurally_added": allvars - missing - semantic}
    birth_count = Counter()
    if lib:
        check(occurrence == len(lib.boolean), "Boolean occurrence directory differs")
        for (op, a, b, c), (i, _) in lib.theory.items():
            if lib.observed(1, i) and op in (3, 4) and c >= 2:
                var = c // 2
                check(var in flags[RULES[op]], "observed theory port outside native role")
                usedt.add(var)
        for ordinal, family, lits, _, _ in lib.births():
            if lits is None:
                continue
            vars_ = {x // 2 for x in lits}
            conclusion.update(vars_)
            birth_count["permanent"] += 1
            birth_count["translated"] += not (vars_ & missing)
            birth_count["touch_other_owner_interval"] += bool(vars_ & revisited)
            birth_count["touch_missing_other_owner_interval"] += bool(vars_ & revisited & missing)
            if exact[ordinal]["mapped"] != str(int(not (vars_ & missing))):
                raise ValueError("independent conclusion classification disagrees")
        union = usedb | usedt
        scopes.update(used_boolean=usedb, used_theory_ports=usedt, used_union=union,
                      used_unmapped=union & missing, permanent_conclusion=conclusion,
                      permanent_conclusion_unmapped=conclusion & missing)
    categories = {v: next((c for c in CATEGORIES[:-1] if v in flags[c]), "unknown") for v in allvars}
    stats, alloc_rows, reason_rows, flag_rows = {}, [], [], []
    for scope, subset in scopes.items():
        counts = Counter(categories[v] for v in subset)
        stats[scope] = {c: counts[c] for c in CATEGORIES} | {"total": len(subset)}
        physical = Counter(allocation[v] for v in subset)
        alloc_rows.extend((case, side, scope, site, op, k) for (site, op), k in sorted(physical.items()))
        flag_rows.extend((case, side, scope, name, len(subset & vals)) for name, vals in sorted(flags.items()))
        if scope in ("final_unmapped", "used_unmapped", "structurally_added", "permanent_conclusion_unmapped"):
            reasons = Counter((pre[v][1], pre[v][2].split(":")[0]) for v in subset)
            reason_rows.extend((case, side, scope, role, why, k) for (role, why), k in sorted(reasons.items()))
    if lib:
        for v in sorted(scopes["used_unmapped"]):
            if v not in defs:
                continue
            chain, seen, at = [], set(), v
            while at not in seen and len(chain) < 12 and at in defs and len(defs[at]) == 1:
                seen.add(at)
                op, out, args = defs[at][0]
                step = dict(variable=at, gate=op, signed_output=out, inputs=args,
                            allocation=allocation[at], final_peer=mu[at], semantic_reason=pre[at][2])
                chain.append(step)
                targets = [x // 2 for x in args if x >= 2 and x // 2 in missing and x // 2 not in seen]
                if not targets:
                    break
                at = targets[0]
            if chain and at not in defs:
                chains = dict(start=v, chain=chain, end=dict(variable=at, category=categories[at],
                    allocation=allocation[at], final_peer=mu[at], semantic_reason=pre[at][2]))
                break
    info = dict(case=case, side=side, atoms=n-1, scopes=stats, cache=dict(cache), births=dict(birth_count),
                native_symbol_types=dict(type_counts), named_port_rows_by_type=dict(value_type),
                constant_port_rows_by_type=dict(port_constants), signed_named_ports=dict(signed_ports),
                gates=dict(gate), sizes=dict(sizes), example_unmapped_gate_chain=chains)
    return info, alloc_rows, reason_rows, flag_rows, all_b


def write_tsv(path, columns, data):
    with path.open("w", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(columns.split())
        w.writerows(data)


def getmaps(directory):
    mu, pre = ({}, {}), ({}, {})
    for row in rows(directory / "effective-map.tsv"):
        side, var, peer = (int(row[k]) for k in ("side", "variable", "peer"))
        check(var not in mu[side], "duplicate map row")
        mu[side][var] = peer
    for side, var, peer, role, why, anchor in fields(directory / "delta/variables.tsv"):
        pre[int(side)][int(var)] = (int(peer), role, why)
    for side in (0, 1):
        for v, peer in mu[side].items():
            if peer >= 2:
                check(mu[1-side].get(peer // 2) == 2*v + peer % 2, "non-injective signed archive map")
    return mu, pre


def support(folder, model, lib, mu, p1_clauses):
    old = {int(x["occurrence"]): int(x["P1_permanent_occurrence"]) for x in rows(folder / "input-matches.tsv")}
    tally, example = Counter(), {}
    occ = 0
    for row in fields(model):
        if row[0] != "C":
            continue
        occ += 1
        if not lib.observed(0, occ - 1):
            continue
        raw = list(map(int, row[2:]))
        targets = [mu[x//2] ^ (x & 1) for x in raw if x >= 2 and mu[x//2] >= 2]
        check(all(x >= 2 for x in raw), "unexpected nonschematic input literal")
        if len(targets) != len(raw):
            why = "untranslated"
            check(old[occ] == -1, "old unmatched receipt")
        else:
            match = p1_clauses.get(tuple(sorted(set(targets))))
            why = "member" if match is not None else "translated_absent"
            check(old[occ] == (match or 0), "full P1 clause or permanent occurrence differs")
        tally[why] += 1
        if why not in example:
            example[why] = dict(occurrence=occ, old_literals=raw, translated_literals=targets if
                                why != "untranslated" else None, unmatched_variables=[x//2 for x in raw
                                if mu[x//2] < 0], production_receipt=old[occ])
    check(sum(tally.values()) == len(old), "wrong UsedLeaf B denominator")
    theories = Counter()
    operations = defaultdict(Counter)
    for r in rows(folder / "theory-matches.tsv"):
        fact = tuple(int(r[k]) for k in ("op", "a", "b", "c"))
        idx, group = lib.theory[fact]
        check(int(r["observed"]) == lib.observed(1, idx) and int(r["group"]) == group, "theory receipt mismatch")
        if int(r["observed"]):
            theories[r["state"]] += 1
            operations[RULES[fact[0]]][r["state"]] += 1
    check(sum(theories.values()) == sum(lib.observed(1,i) for i in range(len(lib.theory))), "UsedLeaf T denominator")
    return dict(boolean=dict(tally), theory=dict(theories), theory_by_rule=operations, boolean_examples=example)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("restored", type=Path, help="restored D43D archive root containing matrix and exact")
    p.add_argument("evidence", type=Path, help="SI-1A output, with published probe/ sidecars")
    p.add_argument("--observed-models", type=Path, help="compare the fresh model prefix to the frozen one")
    args = p.parse_args()
    out = args.evidence
    formal = BASE / "reports/evidence/d43e"
    e_maps = json.loads((formal / "actual-maps.json").read_text())
    frozen_index = json.loads((BASE / "reports/evidence/d43d/raw/files.json").read_text())["files"]
    details, receipts, comparisons, evidence_sources = {}, {}, {}, {}
    allocations, reasons, flags, census = [], [], [], []
    for case in load():
        matrix = args.restored / "matrix" / case
        p0 = matrix / "compact/P0/native"
        p1 = matrix / "compact-reuse/P1/native"
        mu, pre = getmaps(p1)
        lib = DenseLibrary((p0 / "dense.bin").read_bytes())
        exact = {int(v["ordinal"]): v for v in rows(args.restored / "exact" / case / "actual-mu-births.tsv")}
        check(len(exact) == len(lib.records), "missing exact birth")
        current = sha(p1 / "effective-map.tsv")
        check(all(x["prep_sha256"]["effective-map.tsv"] == current for x in e_maps[case].values()), "E map changed")
        details[case], receipts[case] = {}, {}
        sources = [p0 / "dense.bin", p0 / "model.tsv", p1 / "boundary.tsv", p1 / "effective-map.tsv",
                   p1 / "delta/variables.tsv", p1 / "input-matches.tsv", p1 / "theory-matches.tsv",
                   args.restored / "exact" / case / "actual-mu-births.tsv"]
        evidence_sources[case] = {str(x.relative_to(args.restored)): sha(x) for x in sources}
        check(all(digest == frozen_index[rel]["sha256"] for rel,digest in evidence_sources[case].items()),
              "unverified frozen D input")
        for i, side in enumerate(("P0", "P1")):
            model = p0 / "model.tsv" if i == 0 else p1 / "boundary.tsv"
            receipt = json.loads((model.parents[1] / "run.json").read_text())
            original = fingerprint(model, receipt["cwd"])
            fresh_receipt = json.loads((out / "probe" / (case + "-" + side + ".json")).read_text())
            trace = out / "probe" / (case + "-" + side + ".tsv.gz")
            check(sha(trace) == fresh_receipt["trace_sha256"], "trace differs from receipt")
            if args.observed_models:
                fresh_model = args.observed_models / case / side / "model.tsv"
                check(sha(fresh_model) == fresh_receipt["model_sha256"], "fresh model bytes")
                measured = fingerprint(fresh_model, fresh_receipt["cwd"])
                check(original == measured, f"model prefix changed: {case}/{side}")
                comparisons[case + "/" + side] = dict(frozen_model_sha256=sha(model), probe_model_sha256=sha(fresh_model),
                    frozen_canonical=original["canonical_sha256"], probe_canonical=measured["canonical_sha256"],
                    ordered_streams_equal=(original["ordered_stream_sha256"] == measured["ordered_stream_sha256"]),
                    row_counts_equal=(original["rows"] == measured["rows"]))
            receipts[case][side] = original
            result, a, r, f, clauses = scan(case, side, model, trace, lib if i == 0 else None, mu[i], pre[i], exact)
            allocations.extend(a)
            reasons.extend(r)
            flags.extend(f)
            for scope, stats in result["scopes"].items():
                census.append([case, side, scope, *[stats[k] for k in CATEGORIES], stats["total"]])
            details[case][side] = result
        details[case]["support"] = support(p1, p0 / "model.tsv", lib, mu[0], clauses)
        print(case, "checked", flush=True)
    save(out / "origins.json", details)
    save(out / "frozen-model-fingerprints.json", receipts)
    save(out / "source-sha256.json", evidence_sources)
    if args.observed_models:
        save(out / "model-equivalence.json", comparisons)
    write_tsv(out / "cohorts.tsv", "case side scope " + " ".join(CATEGORIES) + " total", census)
    write_tsv(out / "allocation-sites.tsv", "case side scope native_allocation_site enclosing_operator atoms", allocations)
    write_tsv(out / "mapping-reasons.tsv", "case side scope previous_role semantic_reason atoms", reasons)
    write_tsv(out / "overlapping-roles.tsv", "case side scope role atoms", flags)


if __name__ == "__main__":
    main()
