"""Read native SC declarations. Only complete, unambiguous semantic keys are comparable."""
from collections import defaultdict
import gzip
import json
from urllib.parse import unquote


class Keys:
    def __init__(self):
        self.table = {}

    def intern(self, *fields):
        key = tuple(fields)
        result = self.table.get(key)
        if result is None:
            result = self.table[key] = len(self.table) + 1
        return result

    def save(self, path):
        with gzip.open(path, "wt") as file:
            for key, number in self.table.items():
                file.write(json.dumps([number, *key], separators=(",", ":")) + "\n")


def exactly_one(values):
    return next(iter(values)) if len(values) == 1 else 0


class Model:
    def __init__(self, path, keys):
        self.path, self.keys = path, keys
        rows = self.rows = defaultdict(list)
        ended = False
        with path.open(encoding="utf-8") as file:
            if file.readline().rstrip("\n") != "DEAGLE-D1\t1":
                raise ValueError("unexpected manifest format")
            for line in file:
                if ended:
                    raise ValueError("extra records after END")
                if line.startswith(("C\t", "G\t")):
                    continue
                tag, *fields = line.rstrip("\n").split("\t")
                rows[tag].append(tuple(unquote(x) if "%" in x else x for x in fields))
                ended = tag == "END"
        if not ended or rows["END"] not in ([("0",)], [("10",)]) or len(rows["N"]) != 1 or len(rows["K"]) != 1:
            raise ValueError("requires one completed native Closure query and one configuration")
        self.nvars = int(rows["N"][0][0])
        self.sites = {sid: keys.intern("site", signature) if status == "unique" else 0
                      for sid, signature, status, *_ in rows["S"]}
        self.context = {"0": 0}
        self.ctx_reason = {}
        for idx, site, birth, caller, *loops in rows["X"]:
            stable = self.sites[site]
            iterations = [(self.sites[s], int(n)) for s, n in zip(loops[::2], loops[1::2])]
            parents = [self.context.get(p, -1) for p in (birth, caller)]
            if not stable or any(s == 0 for s, _ in iterations):
                reason = "ambiguous_static_site"
            elif min(parents) < 0:
                reason = "unresolved_birth_or_call_context"
            else:
                reason = ""
            self.ctx_reason[idx] = reason
            self.context[idx] = -1 if reason else keys.intern("execution", stable, *parents, tuple(sorted(iterations)))

        self.events, self.event_reason = self.index(rows["E"], "event")
        self.defs, self.def_reason = self.index(rows["V"], "value")
        self.value_types = defaultdict(set)
        for sym, _, _, _, typ, _ in rows["V"]:
            self.value_types[sym].add(typ)
        self.event_info = {e[0]: e[2:] for e in rows["E"]}
        self.node = {i: (name, addr, read, write, parent) for i, name, addr, read, write, parent in rows["NODE"]}
        self.names = {d[0]: i for i, d in self.node.items()}
        self.alias = defaultdict(set)
        self.roles = defaultdict(set)
        self.reasons = defaultdict(set)
        self.folded = defaultdict(set)
        self.alias_lits = defaultdict(set)
        self.sym_roles = defaultdict(set)
        for sym, w, r in rows["F"]:
            a, b = self.event(w), self.event(r)
            self.sym_roles[sym].add(keys.intern("RF", a, b) if a and b else 0)
        for name, raw in rows["GUARD"]:
            e = self.event(name)
            self.add_alias(int(raw), keys.intern("Guard", e) if e else 0, "Guard", self.event_reason.get(name))
        for kind, a, b, raw, *rest in rows["EDGE"]:
            if kind.lower() != "rf":
                continue
            u, v = self.event(a), self.event(b)
            self.add_alias(int(raw), keys.intern("RF", u, v) if u and v else 0, "RF", "unresolved_rf_endpoint")
        for symbol, typ, bit, lit in rows["A"]:
            if symbol in self.sym_roles and typ == "bool" and bit == "0":
                for role in self.sym_roles[symbol]:
                    self.add_alias(int(lit), role, "RF", "unresolved_rf_endpoint")
                continue
            anchors = self.defs.get(symbol, ())
            if not typ or not anchors or symbol in self.def_reason:
                self.add_alias(int(lit), 0, "Value", self.def_reason.get(symbol, "unregistered_symbol_or_type"))
                continue
            if self.value_types[symbol] != {typ}:
                self.add_alias(int(lit), 0, "Value", "inconsistent_native_bit_type")
                continue
            for anchor in anchors:
                self.add_alias(int(lit), keys.intern("bit", anchor, typ, int(bit)), "Value")
        self.dynamic = set()
        for _, _, fwd, rev, *_ in rows["CO"]:
            for lit in (int(fwd), int(rev)):
                if lit >= 0:
                    self.dynamic.add(lit // 2)
                    self.roles[lit // 2].add("CO")
                    self.reasons[lit // 2].add("dynamic_co")
        self.checks = defaultdict(list)

    def index(self, records, family):
        groups, reverse, bad = defaultdict(set), defaultdict(set), {}
        for name, ctx, role, object_key, typ, storage in records:
            if ctx == "-2" and storage == "static" and role == "write":
                execution = self.keys.intern("initial_write", object_key)
            else:
                execution = self.context.get(ctx, -1)
            if execution <= 0:
                bad[name] = self.ctx_reason.get(ctx) or "missing_dynamic_context"
                continue
            if role not in ("spawn", "fence") and (not object_key or not typ):
                bad[name] = "unsupported_object_or_type"
                continue
            stable = self.keys.intern(family, execution, role, object_key, typ)
            groups[name].add(stable)
            reverse[stable].add(name)
        for name, ids in groups.items():
            if any(len(reverse[i]) != 1 for i in ids) or (family == "event" and len(ids) != 1):
                bad[name] = "ambiguous_dynamic_definition"
        return groups, bad

    def event(self, name):
        return 0 if name in self.event_reason else exactly_one(self.events.get(name, ()))

    def add_alias(self, lit, key, role, reason=None):
        if lit < -2:
            raise ValueError(f"unrecognized native literal sentinel {lit}")
        if key:
            self.alias_lits[key].add(lit)
        if lit < 0:
            self.folded[role].add((key, lit))
            return
        var = lit // 2
        self.roles[var].add(role)
        if key:
            self.alias[var].add((key, lit % 2))
        else:
            self.reasons[var].add(reason or "unresolved_semantic_alias")

    def write_anchors(self, peer, path):
        # Every role is checked in both directions. The first entry only fixes sign convention.
        alias_groups = {}
        for var in self.roles:
            entries = sorted(self.alias[var])
            errors = self.reasons[var]
            for key, _ in entries:
                ours, theirs = self.alias_lits[key], peer.alias_lits.get(key, set())
                if len(ours) != 1:
                    errors.add("local_alias_collision")
                if len(theirs) > 1:
                    errors.add("peer_alias_split_or_collision")
                elif not theirs:
                    errors.add("peer_alias_absent")
                elif next(iter(theirs)) < 0:
                    errors.add("peer_constant_fold")
            if entries and not errors:
                sign = entries[0][1]
                ident = self.keys.intern("signed_alias_class", tuple((key, pol ^ sign) for key, pol in entries))
                alias_groups[var] = (ident, sign)
        with path.open("w") as file:
            for var in sorted(self.roles):
                key, sign = alias_groups.get(var, (0, 0))
                file.write(f"{var}\t{key}\t{sign}\t{'+'.join(sorted(self.roles[var]))}\t"
                           f"{','.join(sorted(self.reasons[var])) or '-'}\n")
