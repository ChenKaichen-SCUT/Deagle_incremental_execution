"""Proofs for original Closure cycle clauses using only declarative SC facts.

Each step establishes strict precedence between two events. The last derives x < x.
A guard becomes true only from a declared constant or an explicit clause premise.
"""
from collections import defaultdict
from .context import atom_key


class Facts:
    def __init__(self, context, clause):
        bindings = {atom_key(r["atom"]): r["binding"] for r in context["atom_bindings"]}
        forced = {}
        for item in clause:
            b = bindings[atom_key(item["atom"])]
            if "representative" not in b:
                raise ValueError("undeclared_or_constant_clause_atom")
            root = atom_key(b["representative"])
            # To falsify the clause, a negative literal's underlying atom is true.
            value = item["negative"] ^ b["opposite"]
            if root in forced and forced[root] != value:
                raise ValueError("tautological_reason")
            forced[root] = value

        def active(key):
            b = bindings[key]
            if "constant" in b:
                return b["constant"]
            value = forced.get(atom_key(b["representative"]))
            return value is not None and value != b["opposite"]

        self.nodes = context["events"]
        self.static = {(e["from"], e["to"]) for e in context["edges"] if e["kind"] in ("po", "apo")}
        self.rf = {(key[1], key[2]) for key in bindings if key[0] == "rf" and active(key)}
        self.writes = {k[1] for k in bindings if k[0]=="guard" and active(k)}
        parent = {node:node for node in self.nodes}
        def find(node):
            while node != parent[node]:
                node = parent[node]
            return node
        for e in context["edges"]:
            if e["kind"] == "apo":
                parent[find(e["from"])] = find(e["to"])
        self.group = {n:find(n) for n in self.nodes}
        self.members = defaultdict(list)
        for n, g in self.group.items():
            self.members[g].append(n)

    def same_address(self, w, v):
        a = self.nodes[w]["solver_address"]
        return a is not None and a == self.nodes[v]["solver_address"]

    def rule(self, rule, a, b, deps):
        if a not in self.nodes or b not in self.nodes:
            return False
        if rule == "static":
            return not deps and (a,b) in self.static
        if rule == "rf":
            return not deps and (a,b) in self.rf
        if rule == "transitive":
            return len(deps)==2 and deps[0][0]==a and deps[0][1]==deps[1][0] and deps[1][1]==b
        if len(deps) != 1:
            return False
        x,y = deps[0]
        if rule == "atomic_block":
            return self.group[x]!=self.group[y] and self.group[a]==self.group[x] and self.group[b]==self.group[y]
        if rule == "from_read":
            # RF(x,a), x < b and both writes are present => a < b.
            return x!=b and y==b and (x,a) in self.rf and {x,b} <= self.writes and self.same_address(x,b)
        if rule == "coherence":
            # RF(b,y), a < y and both writes are present => a < b.
            return a!=b and x==a and (b,y) in self.rf and {a,b} <= self.writes and self.same_address(a,b)
        return False


def derive(context, clause):
    facts = Facts(context, clause)
    if len(facts.nodes) > 256:
        raise ValueError("certificate_node_budget")
    records = {}
    successors, predecessors = defaultdict(set), defaultdict(set)
    todo = []

    def add(a, b, rule, deps=()):
        if (a,b) not in records:
            records[a,b] = (rule,deps)
            todo.append((a,b))
            successors[a].add(b)
            predecessors[b].add(a)

    for a,b in sorted(facts.static):
        add(a,b,"static")
    for a,b in sorted(facts.rf):
        add(a,b,"rf")
    head = 0
    while head < len(todo):
        a,b = todo[head]
        head += 1
        if a == b:
            proof, indexes = [], {}
            def emit(pair):
                if pair not in indexes:
                    rule, deps = records[pair]
                    refs = [emit(dep) for dep in deps]
                    indexes[pair] = len(proof)
                    proof.append({"rule":rule,"edge":list(pair),"uses":refs})
                return indexes[pair]
            emit((a,b))
            return proof
        for x in sorted(predecessors[a]):
            add(x,b,"transitive",((x,a),(a,b)))
        for y in sorted(successors[b]):
            add(a,y,"transitive",((a,b),(b,y)))
        if facts.group[a] != facts.group[b]:
            for x in facts.members[facts.group[a]]:
                for y in facts.members[facts.group[b]]:
                    add(x,y,"atomic_block",((a,b),))
        for w,r in facts.rf:
            if w not in facts.writes:
                continue
            if a==w and b!=w and b in facts.writes and facts.same_address(w,b):
                add(r,b,"from_read",((a,b),))
            if b==r and a!=w and a in facts.writes and facts.same_address(w,a):
                add(a,w,"coherence",((a,b),))
    raise ValueError("no_theory_only_cycle_certificate")


def check(context, clause, proof):
    facts = Facts(context, clause)
    inferred = []
    for row in proof:
        refs = row["uses"]
        if any(type(i) is not int or not 0 <= i < len(inferred) for i in refs):
            return False
        a,b = row["edge"]
        if not facts.rule(row["rule"], a, b, [inferred[i] for i in refs]):
            return False
        inferred.append((a,b))
    return bool(inferred and inferred[-1][0] == inferred[-1][1])
