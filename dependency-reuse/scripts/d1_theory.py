"""Reconstruct scoped SC leaves from the installed graph and the observed expression DAG."""
from collections import defaultdict
from functools import lru_cache
from itertools import combinations


class Terms:
    # Scalar operations with no extra named attributes required for their meaning.
    OPS = {"and", "or", "xor", "not", "if", "=", "notequal", "!=", "+", "-", "*",
           "unary-", "/", "div", "mod", "<", ">", "<=", ">=", "typecast", "bitand",
           "bitor", "bitxor", "bitnot", "shl", "lshr", "ashr", "implies"}

    def __init__(self, m):
        self.model, self.active = m, set()
        self.terms = {t[0]: t[1:] for t in m.rows["TERM"]}
        self.rhs = defaultdict(set)
        for sym, term in m.rows["VALUE_DEF"]:
            self.rhs[sym].add(term)
        self.read = {v[0] for v in m.rows["V"] if v[2] == "read"}

    @lru_cache(None)
    def expression(self, term):
        if term in self.active:
            return 0, "cyclic_ssa_definition"
        m = self.model
        op, typ, data, *children = self.terms[term]
        if not typ:
            return 0, "unsupported_expression_type"
        if op == "constant" and not children:
            return m.keys.intern("constant", typ, data), ""
        self.active.add(term)
        try:
            if op == "symbol":
                defs = self.rhs.get(data, set())
                if data not in self.read and defs:
                    if len(defs) != 1:
                        return 0, "ambiguous_rhs"
                    return self.expression(next(iter(defs)))
                if data in m.sym_roles:
                    values = m.sym_roles[data]
                else:
                    values = m.defs.get(data)
                if not values or 0 in values or data in m.def_reason:
                    return 0, "unresolved_expression_symbol"
                return m.keys.intern("value_reference", typ, tuple(sorted(values))), ""
            if op not in self.OPS or not children:
                return 0, "unsupported_expression_operator:" + op
            operands = []
            for child in children:
                key, why = self.expression(child)
                if not key:
                    return 0, why
                operands.append(key)
            return m.keys.intern("expression", op, typ, tuple(operands)), ""
        finally:
            self.active.remove(term)


def declarations(m, translated):
    keys, rows = m.keys, m.rows
    result = []
    def add(kind, local, slot, fields=None, why=""):
        stable = keys.intern("declaration", kind, *fields) if fields is not None else 0
        result.append((kind, local, slot, stable, why))
    def signed(raw):
        raw = int(raw)
        if raw in (-2, -1):
            return raw + 2
        if raw < 2 or raw // 2 not in translated:
            return -1
        return translated[raw // 2] ^ (raw & 1)
    def address(name):
        info = m.event_info.get(name)
        # Only scalar storage with a globally anchored designator has a version-independent address interpretation.
        if not info or info[3] != "static" or not info[2] or not info[1].startswith("6:symbol"):
            return 0
        return keys.intern("static_address", info[1])
    def eid(node):
        return m.event(m.node[node][0]) if node in m.node else 0
    add("RuleConfig", "native-SC", "config", rows["K"][0])
    for name in sorted(m.event_info):
        e = m.event(name)
        add("EventIdentity", name, e, [e] if e else None,
            "" if e else m.event_reason.get(name, "missing_event"))
    addr_groups, writes, readers, bounds = (defaultdict(list) for _ in range(4))
    for node, (name, addr, r, w, parent) in m.node.items():
        e = m.event(name)
        info = m.event_info.get(name, ("?", "", "", ""))
        a = address(name)
        ok = e and (a or info[0] in ("spawn", "fence"))
        add("EventSchema", name, e, [e, info[0], a, info[2], r, w] if ok else None,
            "" if ok else m.event_reason.get(name, "unresolved_address_interpretation"))
        if r or w:
            addr_groups[addr].append(node)
            if w: writes[addr].append(node)
            if r: readers[addr].append(node)
        seen = set()
        while m.node[parent][4] != parent:
            if parent in seen:
                raise ValueError("cycle in native union-find")
            seen.add(parent)
            parent = m.node[parent][4]
        bounds[parent].append(node)
    for addr, members in addr_groups.items():
        for i, j in combinations(members, 2):
            u, v = eid(i), eid(j)
            a, b = (address(m.node[n][0]) for n in (i, j))
            pair = tuple(sorted((u, v)))
            ok = u and v and a and a == b
            add("SameAddress", [i, j], pair, [pair, a] if ok else None,
                "" if ok else "unresolved_endpoint_or_native_address")
        for n in readers[addr]:
            r = eid(n)
            ws = [eid(w) for w in writes[addr]]
            storage = address(m.node[n][0])
            ok = r and storage and all(ws) and all(address(m.node[w][0]) == storage for w in writes[addr])
            add("CompleteWriteDomain", n, r, [r, storage, tuple(sorted(ws))] if ok else None,
                "" if ok else "incomplete_address_write_domain")
    members = defaultdict(set)
    for root, item in rows["MEMBER"]:
        members[root].add(item)
    internal = {tag: defaultdict(set) for tag in ("IN", "OUT")}
    for tag, groups in internal.items():
        for i, j in rows[tag]: groups[i].add(j)
    for root, nodes in bounds.items():
        node_set = set(nodes)
        es = tuple(sorted(eid(n) for n in nodes))
        consistent = members[root] == node_set
        edges = []
        for tag in ("IN", "OUT"):
            pairs = []
            for i in nodes:
                for j in internal[tag][i]:
                    if j not in node_set: consistent = False
                    pairs.append((eid(i), eid(j)))
            edges.append(tuple(sorted(pairs)))
        out_edges = {(b, a) for a, b in edges[0]}
        consistent = consistent and out_edges == set(edges[1])
        ok = consistent and all(es)
        add("BlockCertificate", sorted(nodes, key=int), es,
            ["native-APO-contiguous", es, *edges] if ok else None,
            "" if ok else ("inconsistent_native_block" if not consistent else "unresolved_block_member"))

    terms = Terms(m)
    guards = defaultdict(set)
    for name, term in rows["H"]:
        guards[name].add(term)
    for name, raw in rows["GUARD"]:
        e, lit = m.event(name), signed(raw)
        definitions = guards[name]
        term, why = terms.expression(next(iter(definitions))) if len(definitions) == 1 else (0, "ambiguous_guard_definition")
        ok = e and term
        add("GuardDefinition", name, e, [e, term] if ok else None,
            "" if ok else why or "unresolved_guard_event")
        ok = ok and lit >= 0
        add("GuardBinding", [name, raw], e, [e, lit, term] if ok else None,
            "" if ok else why or ("unmapped_guard_literal" if e else "unresolved_guard_event"))

    for sym, definitions in terms.rhs.items():
        ids = m.defs.get(sym, ())
        slot = tuple(sorted(ids))
        term, why = terms.expression(next(iter(definitions))) if len(definitions) == 1 else (0, "ambiguous_rhs")
        ok = slot and sym not in m.def_reason and term
        add("ValueDefinition", sym, slot, [slot, term] if ok else None,
            "" if ok else why or m.def_reason.get(sym, "unresolved_value_definition"))
    candidates = defaultdict(set)
    for kind, a, b, raw, f, t, pair_raw in rows["EDGE"]:
        u,v = m.event(a), m.event(b)
        pair = (u, v)
        k = kind.lower()
        if k == "rf":
            candidates[b].add(a)
            add("RFIdentity", [a,b], pair, [u,v] if u and v else None,
                "" if u and v else "unresolved_rf_endpoint")
            lit = signed(raw)
            binding = f == m.names.get(a) and t == m.names.get(b) and raw == pair_raw
            ok = u and v and lit >= 0 and binding
            add("RFBinding", [a,b,raw], pair, [u,v,lit] if ok else None,
                "" if ok else ("shadowed_native_rf_binding" if not binding else
                               "unresolved_rf_endpoint" if not (u and v) else "unmapped_rf_literal"))
        elif k in ("po","apo"):
            # Native Closure unconditionally activates these declared edge kinds.
            add(k.upper(), [a,b], pair, [u,v] if u and v else None,
                "" if u and v else "unresolved_order_endpoint")
        else:
            add("OtherEdge", [kind,a,b], pair, None, "unsupported_edge_kind:" + kind)
    for nodes in readers.values():
        for n in nodes:
            name = m.node[n][0]
            r = m.event(name)
            ws = [m.event(w) for w in candidates[name]]
            ok = r and all(ws)
            add("CompleteRFDomain", name, r, [r, tuple(sorted(ws))] if ok else None,
                "" if ok else "unresolved_rf_candidate")
    for raw in rows["CO"]:
        add("DynamicCO", raw, (), None, "search_allocated_co")
    query_lits = [signed(a) for a in rows["N"][0][1:]]
    complete = len(rows["QUERY"]) == 1 and bool(rows["TARGET"]) and all(l >= 0 for l in query_lits)
    add("QueryScope", rows["TARGET"], "query",
        [tuple(sorted(t[0] for t in rows["TARGET"])), tuple(sorted(query_lits))] if complete else None,
        "" if complete else "unresolved_query_scope")
    for assumption in rows["N"][0][1:]:
        lit = signed(assumption)
        add("QueryAssumption", assumption, "query", [tuple(sorted(rows["TARGET"])),lit] if lit >= 0 else None,
            "" if lit >= 0 else "unmapped_assumption")
    return result
