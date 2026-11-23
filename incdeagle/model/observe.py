"""Translate one real postprocessed equation into typed, source-addressable records."""
from collections import Counter, defaultdict
from functools import lru_cache
import re

from .identity import GotoMap, contexts, digest, read, step_identity

EVENTS = {"read", "write", "spawn", "fence"}
FORMULAS = {"assignment", "assume", "assert", "constraint", "goto"}


class Expressions:
    def __init__(self, raw, bindings):
        self.raw, self.bindings, self.nodes = raw, bindings, {}

    @lru_cache(None)
    def translate(self, index):
        if index is None:
            return None, frozenset(), True
        node = self.raw[index]
        fields = {k: v for k, v in node.get("named", {}).items() if k not in {"#source_location", "#end_location"}}
        tag = node["id"]
        deps, ok = set(), True
        value = {"operator": tag, "fields": {}, "operands": []}
        if tag == "symbol" and "identifier" in fields:
            name = self.raw[fields["identifier"]]["id"]
            binding = self.bindings.get(name)
            if binding:
                symbol, ok = binding
                deps.add(symbol)
            elif re.search(r"[!@#]\d|\$\d+\$|^memory_model::|^symex::", name):
                base = re.split(r"[!@#]\d|\$\d+\$", name)[0]
                if base.startswith(("memory_model::", "symex::")):
                    base = re.sub(r"\d+", "?", base)
                symbol, ok = "unresolved:" + base, False
                deps.add(symbol)
            else:
                symbol = "source:" + name
                deps.add(symbol)
            value["symbol"] = symbol
            fields = {k: v for k, v in fields.items() if k not in
                      {"identifier", "L0", "L1", "L2", "L1_object_identifier", "expression"}}
        for key, ref in fields.items():
            child, names, good = self.translate(ref)
            value["fields"][key] = child
            deps.update(names)
            ok = ok and good
        for ref in node.get("sub", []):
            child, names, good = self.translate(ref)
            value["operands"].append(child)
            deps.update(names)
            ok = ok and good
        # Commutative Boolean choice sets can be emitted in allocator-dependent order.
        if tag in {"and", "or", "equal", "notequal"}:
            value["operands"].sort()
        result = digest(value)
        self.nodes[result] = value
        return result, frozenset(deps), ok


def summarize(doc):
    return {"steps": len(doc["steps"]), "step_kinds": dict(Counter(s["kind"] for s in doc["steps"])),
            "events": sum(s["kind"] in EVENTS for s in doc["steps"]), "oc_guards": len(doc["oc_guards"]),
            "edge_kinds": dict(Counter(e["kind"] for e in doc["oc_edges"])),
            "constraint_comments": dict(Counter(s.get("comment", "") for s in doc["steps"] if s["kind"] == "constraint")),
            "properties": [s.get("property") for s in doc["steps"] if s["kind"] == "assert"]}


def build_model(directory, target):
    goto = read(directory / "goto.json")
    raw, sc, full = (read(directory / (name + ".json")) for name in ("raw_ssa", "sc_input", "full_model"))
    visits = read(directory / "visits.json")
    static = GotoMap(directory, goto)
    threads, dispatches = contexts(static, visits, full["thread_births"])
    steps, graph = full["steps"], full["oc_edges"]
    keys = [step_identity(s, static, threads, dispatches) for s in steps]
    ids = [digest(k) for k, _ in keys]
    multiplicity = Counter(ids)
    event_indices = [i for i, s in enumerate(steps) if s["kind"] in EVENTS]
    sc_group_members, sc_groups = defaultdict(list), defaultdict(list)
    for s in sc["steps"]:
        if s["kind"] in {"read", "write"}:
            skey, ok = step_identity(s, static, threads, dispatches)
            identity = digest(skey)
            group = s["local_source_group"]
            sc_group_members[group].append((identity, ok))
            sc_groups[identity].append(group)
    event_names, definitions, sections, address_instances = {}, defaultdict(list), {}, defaultdict(set)
    for i, s in enumerate(steps):
        if s["kind"] == "assignment":
            definitions[s.get("local_symbol")].append(i)
        if s["kind"] == "atomic_begin":
            sections[s["atomic_section"]] = i
        if "oc_name" in s and s["kind"] in EVENTS:
            event_names.setdefault(s["oc_name"], []).append(i)
        if s["kind"] in EVENTS and s.get("object"):
            address_instances[s["object"]].add(s["address_l1"])

    def usable(i):
        return (keys[i][1] and multiplicity[ids[i]] == 1
                and len(address_instances.get(steps[i].get("object"), ())) <= 1)

    def endpoint(name):
        choices = event_names.get(name, [])
        if len(choices) == 1:
            i = choices[0]
            return ids[i], usable(i)
        return "unresolved-endpoint", False

    bindings = {}
    for i, s in enumerate(steps):
        sym = s.get("local_symbol")
        if sym and s["kind"] in {"decl", "assignment"}:
            # Assignments can have an accompanying DECL with the very same symbol.
            if s["kind"] == "assignment" or sym not in bindings:
                bindings[sym] = ("definition:" + ids[i], usable(i) and len(definitions[sym]) <= 1)
    for i in event_indices:
        sym = steps[i].get("local_symbol")
        if sym:
            bindings[sym] = ("event:" + ids[i], usable(i))
    neighbors, rf_info = defaultdict(list), {}
    for edge in graph:
        a, a_ok = endpoint(edge["from"])
        b, b_ok = endpoint(edge["to"])
        if edge["kind"] in {"po", "apo"}:
            neighbors[a].append(("out", edge["kind"], b, b_ok))
            neighbors[b].append(("in", edge["kind"], a, a_ok))
        if edge["kind"] == "rf":
            g = full["ireps"][edge["guard"]]
            if g["id"] == "symbol":
                name = full["ireps"][g["named"]["identifier"]]["id"]
                rf = "rf:" + digest([a, b])
                bindings[name] = (rf, a_ok and b_ok)
                rf_info[rf] = [a, b]
    expr = Expressions(full["ireps"], bindings)
    guard_map = {g["local_symbol"]: g for g in full["oc_guards"]}
    events, fragments = [], []

    def translated(refs):
        fields, deps, good = {}, set(), True
        for label, ref in refs.items():
            key, names, ok = expr.translate(ref)
            fields[label] = key
            deps.update(names)
            good = good and ok
        return fields, deps, good

    for i in event_indices:
        s = steps[i]
        sym = s.get("local_symbol")
        defined = definitions.get(sym, [])
        atom = sections.get(s["atomic_section"])
        adj = sorted(neighbors[ids[i]])
        groups = sc_groups.get(ids[i], [])
        same_source = sc_group_members[groups[0]] if len(groups) == 1 else []
        guard = guard_map.get(sym, {})
        typ = full["ireps"][s["lhs"]].get("named", {}).get("type") if s["lhs"] is not None else None
        value_ref = steps[defined[0]]["rhs"] if s["kind"] == "write" and len(defined) == 1 else s["lhs"]
        fields, deps, expr_ok = translated({"guard": s["guard"], "oc_guard": guard.get("guard"),
                                           "value": value_ref, "type": typ})
        semantic = {**fields, "object": s.get("object"), "role": s["kind"],
                    "atomic_region": ids[atom] if atom is not None else None,
                    "ordering": [list(entry[:3]) for entry in adj],
                    "sc_same_source": [key for key, _ in same_source],
                    "solver_line": int(guard.get("solver_line") or "0") if guard else None}
        okay = (usable(i) and expr_ok and all(e[3] for e in adj)
                and (s["kind"] not in {"read", "write"} or (len(groups) == 1 and all(ok for _, ok in same_source)))
                and (s["kind"] != "write" or len(defined) == 1)
                and (not s["atomic_section"] or (atom is not None and usable(atom))))
        deps.update("event:" + e[2] for e in adj)
        deps.update("event:" + key for key, _ in same_source if key != ids[i])
        events.append({"id": ids[i], "key": keys[i][0], "semantic": semantic, "fingerprint": digest(semantic),
                       "identity_unique": usable(i), "comparable": okay, "dependencies": sorted(deps),
                       "bucket": s.get("object"), "thread": keys[i][0]["thread"], "native_step": i})

    by_event = {e["id"]: e for e in events}

    def fragment(kind, owner, refs, extra_deps, valid, thread_ids, buckets, extra):
        typed, symbols, expr_ok = translated(refs)
        deps = set(extra_deps) | symbols
        for sym in symbols:
            if sym in rf_info:
                deps.update("event:" + key for key in rf_info[sym])
        for dep in deps:
            ev = by_event.get(dep.removeprefix("event:")) if dep.startswith("event:") else None
            if ev:
                thread_ids.add(ev["thread"])
                if ev["bucket"]:
                    buckets.add(ev["bucket"])
        payload = {"kind": kind, "owner": owner, "typed_expression": typed, "semantics": extra,
                   "symbols": sorted(symbols), "dependencies": sorted(deps), "threads": sorted(thread_ids),
                   "buckets": sorted(buckets)}
        fragments.append({**payload, "fingerprint": digest(payload), "comparable": bool(valid and expr_ok)})

    for i, s in enumerate(steps):
        if s["kind"] not in FORMULAS:
            continue
        kind = s.get("comment", "constraint") if s["kind"] == "constraint" else s["kind"]
        from_sc = s["kind"] == "constraint"
        owner = None if from_sc else ids[i]
        addr = {s["object"]} if s.get("object") else set()
        extra = {"ignored": s["ignored"], "property": s.get("property"), "assignment_type": s["assignment_type"]}
        fragment(kind, owner, {k: s[k] for k in ("guard", "condition", "lhs", "rhs", "full_lhs")},
                 [], from_sc or usable(i), {keys[i][0]["thread"]}, addr, extra)
    for edge in graph:
        a, a_ok = endpoint(edge["from"])
        b, b_ok = endpoint(edge["to"])
        fragment("edge-" + edge["kind"], None, {"guard": edge["guard"]}, ["event:" + a, "event:" + b],
                 a_ok and b_ok, set(), set(), {"from": a, "to": b})
    counts = {doc["phase"]: summarize(doc) for doc in (raw, sc, full)}
    counts["symbolic_instruction_dispatches"] = len(visits)
    counts["constraint_fragments"] = len(fragments)
    props = counts["full_model"]["properties"]
    model = {"schema": 1, "mappings": static.export(), "layout": goto["layout"], "events": events,
             "fragments": fragments, "typed_nodes": expr.nodes, "counts": counts, "target": target,
             "unwinding_properties": [p for p in props if "unwind" in p.split(".")]}
    # Layout, structural contents and multiplicities participate; raw row order, PCs
    # and display locations do not. Solver-consumed locations are in fingerprints.
    signature = {"layout": model["layout"], "counts": counts,
                 "sources": sorted((k, v["unique"]) for k, v in static.sources.items()),
                 "goto": sorted((k, v["unique"], sorted(v["targets"])) for k, v in static.rows.items()),
                 "events": sorted((e["id"], e["fingerprint"], e["comparable"]) for e in events),
                 "fragments": sorted((f["fingerprint"], f["comparable"]) for f in fragments)}
    model["structure_sha256"] = digest(signature)
    return model
