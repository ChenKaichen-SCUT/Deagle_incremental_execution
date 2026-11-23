"""Freeze the graph delivered to Closure, independent of this solver's SAT numbering."""
from collections import defaultdict
from functools import lru_cache

from incdeagle.model.identity import GotoMap, contexts, digest, read, step_identity
from incdeagle.model.observe import EVENTS

SCHEMA = 1
BACKEND = "Deagle Closure / MiniSat core / SC"


def atom_key(atom):
    if atom["kind"] == "rf":
        return ("rf", atom["write"], atom["read"])
    if atom["kind"] == "guard":
        return ("guard", atom["event"])
    raise ValueError("unsupported_atom_kind")


def event_atom(kind, *nodes):
    if kind == "rf":
        return {"kind": kind, "write": nodes[0], "read": nodes[1]}
    return {"kind": "guard", "event": nodes[0]}


class Registry:
    """Keep both literal polarity and the complete alias group. Raw x is process-local."""
    def __init__(self, atoms):
        self.by_key = {}
        self.by_var = defaultdict(list)
        for atom, raw, slot in atoms:
            key = atom_key(atom)
            if key in self.by_key or raw < -2:
                raise ValueError("duplicate_atom_or_unknown_literal")
            self.by_key[key] = (atom, raw, slot)
            if raw >= 0:
                self.by_var[raw // 2].append(key)
        for group in self.by_var.values():
            group.sort()
        self.declarations = []
        for key, (atom, raw, _) in sorted(self.by_key.items()):
            if raw < 0:
                binding = {"constant": raw == -1}
            else:
                pivot = self.by_key[self.by_var[raw // 2][0]]
                binding = {"representative": pivot[0], "opposite": bool((pivot[1] ^ raw) & 1)}
            self.declarations.append({"atom": atom, "binding": binding})

    def decode_clause(self, literals):
        resolved = {}
        for x in literals:
            if x < 0 or x // 2 not in self.by_var:
                raise ValueError("unmapped_dynamic_co_or_special_literal")
            key = self.by_var[x // 2][0]
            atom, raw, _ = self.by_key[key]
            negative = bool((x ^ raw) & 1)
            if key in resolved and resolved[key]["negative"] != negative:
                raise ValueError("tautological_reason")
            resolved[key] = {"atom": atom, "negative": negative}
        if not resolved:
            raise ValueError("unsupported_empty_reason")
        return [resolved[k] for k in sorted(resolved)]

    def bind(self, clause):
        if not clause:
            raise ValueError("unsupported_empty_reason")
        result = []
        seen_variables = set()
        for item in clause:
            _, raw, slot = self.by_key[atom_key(item["atom"])]
            if raw < 0 or type(item["negative"]) is not bool:
                raise ValueError("changed_constant_or_invalid_polarity")
            if raw // 2 in seen_variables:
                raise ValueError("duplicate_or_complementary_bound_variable")
            seen_variables.add(raw // 2)
            result.append((slot, int(item["negative"])))
        return result


def freeze(directory, settings, manifest):
    native = read(directory / "native-bindings.json")
    if native["site"] != "bmc_util before save_raw_graph/init":
        raise ValueError("late_or_unknown_graph_snapshot")
    model = read(directory / "full_model.json")
    goto = read(directory / "goto.json")
    visits = read(directory / "visits.json")
    mapping = GotoMap(directory, goto)
    threads, path = contexts(mapping, visits, model["thread_births"])
    coords = {(r["function"], r["pc"]): {k: r[k] for k in ("function","pc","file","line","column","kind")}
              for r in goto["instructions"]}

    def site(ref):
        return coords[ref["function"], ref["pc"]]

    pool = model["ireps"]
    @lru_cache(None)
    def expression(index):
        if index is None:
            return None
        term = pool[index]
        return [term["id"], {k: expression(v) for k, v in term.get("named", {}).items()},
                [expression(v) for v in term.get("sub", [])]]

    nodes, names, atomics = {}, {}, defaultdict(list)
    for step in model["steps"]:
        if step["kind"] not in EVENTS:
            continue
        # Add actual source coordinates and dynamic frame locations to the stage-3
        # identity. This permits exact-site alignment even for modeled library code.
        visit = step["visit"]
        if visit <= 0 or visit > len(visits) or step["thread"] not in threads:
            raise ValueError("unmapped_event_visit_or_thread")
        v = visits[visit-1]
        if v["thread"] != step["thread"]:
            raise ValueError("unmapped_event_thread")
        stable, _ = step_identity(step, mapping, threads, path)
        identity = {"stage3": stable, "source": site(step), "dispatch": site(v),
                    "frames": v["frames"], "thread": step["thread"]}
        uid = digest(identity)
        if uid in nodes:
            raise ValueError("ambiguous_event_identity")
        name = step.get("oc_name")
        if name:
            if name in names:
                raise ValueError("ambiguous_native_endpoint")
            names[name] = uid
        type_id = pool[step["lhs"]].get("named", {}).get("type") if step["lhs"] is not None else None
        nodes[uid] = {"identity": identity, "role": step["kind"], "object": step.get("object"),
                      "address_l1": step.get("address_l1"), "type": expression(type_id),
                      "event_guard": expression(step["guard"]), "solver_address": native["addresses"].get(name)}
        if step["atomic_section"]:
            atomics[step["atomic_section"]].append(uid)
    if set(native["addresses"]) != set(names):
        raise ValueError("unmapped_graph_endpoint")
    edges, atoms = [], []
    rf_dispatch = set()
    converted = native["edges"]
    if len(converted) != len(model["oc_edges"]):
        raise ValueError("edge_conversion_mismatch")
    for idx, (edge, decl) in enumerate(zip(converted, model["oc_edges"])):
        kind = edge["kind"]
        if (any(edge[k] != decl[k] for k in ("kind","from","to")) or
                edge["slot"] != idx or kind not in ("rf","apo","po")):
            raise ValueError("unsupported_or_mismatched_edge")
        a, b, raw = names[edge["from"]], names[edge["to"]], edge["x"]
        edge_doc = {"kind": kind, "from": a, "to": b}
        if kind == "rf":
            if raw < 0 or raw in rf_dispatch or pool[decl["guard"]]["id"] != "symbol":
                raise ValueError("ambiguous_or_nonvariable_rf")
            rf_dispatch.add(raw)
            atoms.append((event_atom("rf",a,b), raw, idx))
        else:
            if raw != -1:
                raise ValueError("nonconstant_static_relation")
            edge_doc["declared_true"] = True
        edges.append(edge_doc)
    locations = {}
    guards = {g["local_symbol"]:g for g in model["oc_guards"]}
    if len(guards) != len(native["guards"]):
        raise ValueError("guard_conversion_mismatch")
    for idx, g in enumerate(native["guards"], len(converted)):
        name, raw = g["event"], g["x"]
        uid = names[name]
        if int(guards[name]["solver_line"] or 0) != g["line"] or g["slot"] != idx:
            raise ValueError("guard_location_or_slot_mismatch")
        locations[uid] = {"line": g["line"], "expression": expression(guards[name]["guard"])}
        atoms.append((event_atom("guard",uid), raw, idx))
    registry = Registry(atoms)
    births = [{"parent": b["parent"], "child": b["child"], "site": site(b), "guard": expression(b["guard"])}
              for b in model["thread_births"]]
    # Include actual edge order (upstream initialization iterates in that order).
    # Data RHS is excluded. Ordering-relevant guards, types and addr partitions are retained.
    context = {"schema": SCHEMA, "backend": BACKEND,
               "engine": settings, "configuration": manifest["context"], "layout": goto["layout"],
               "events": nodes, "threads": births, "atomic_sections": sorted(sorted(s) for s in atomics.values()),
               "edges": edges, "guard_locations": locations, "atom_bindings": registry.declarations}
    return context, registry
