"""Research-only proof cache and strict finite search, separate from the permutation oracle."""
from collections import Counter
from dataclasses import dataclass
from itertools import product

from reference import active, valuations
from proof import replay

RULES = ("rules", "finite-sc-po-rf-fr-ws-block-v1")


@dataclass(frozen=True)
class Proof:
    rule: str
    parents: tuple
    local: frozenset
    leaves: frozenset


class Branch:
    def __init__(self, graph, env, chosen):
        self.by = graph.validate()
        self.on = {k for k,e in self.by.items() if active(e, env)}
        self.selected = set(chosen)
        self.groups = {k: frozenset([k]) for k in self.by}
        for a,b in graph.apo:
            group = self.groups[a] | self.groups[b]
            for k in group:
                self.groups[k] = group

        self.signature = {}
        self.membership = {}
        self.order = set()
        self.available = {RULES}
        for k,e in self.by.items():
            self.signature[k] = ("event", k, e.thread, e.op, e.addr, e.typ, e.guard)
            self.available.add(self.signature[k])
            if k in self.on:
                self.available.add(("true", k, e.guard))
            self.membership[k] = ("block",) + tuple(sorted(self.groups[k]))
            self.available.add(self.membership[k])
        for kind,items in (("po",graph.po),("apo",graph.apo)):
            for a,b in items:
                self.available.add((kind,a,b))
                self.order.add((a,b,kind))
        self.available.update(("decl-rf",w,r) for w,r in graph.rf)
        self.available.update(("select",w,r) for w,r in self.selected)

    def endpoints(self, *keys):
        return {leaf for k in keys for leaf in (self.signature[k], ("true",k,self.by[k].guard))}

    def static_paths(self):
        # Unlike the oracle, record an actual static path for each projected constraint.
        for start in sorted(self.on):
            queue = [(start,frozenset())]
            visited = set()
            for u, path in queue:
                for a,b,kind in sorted(self.order):
                    if a != u or b in visited:
                        continue
                    visited.add(b)
                    support = path | {(kind,a,b), self.signature[a], self.signature[b]}
                    if b in self.on:
                        yield start,b,support
                    queue.append((b,support))


def saturate(branch, old=None):
    facts = {}
    stats = Counter()
    for pair, proof in (old or {}).items():
        if replay(branch,pair,proof,facts,RULES):
            facts[pair] = proof
            stats["retained"] += 1
            if proof.parents:
                stats["retained_with_derived_parents"] += 1
        else:
            stats["discarded"] += 1
            if proof.parents:
                stats["discarded_with_derived_parents"] += 1

    def add(a,b,rule,parents=(),extra=()):
        if (a,b) in facts:
            return
        local = frozenset({RULES} | branch.endpoints(a,b) | set(extra))
        leaves = local.union(*(facts[p].leaves for p in parents))
        if not leaves <= branch.available:
            raise AssertionError((rule, leaves - branch.available))
        facts[a,b] = Proof(rule,tuple(parents),local,leaves)
        stats["inserted"] += 1

    for a,b,path in branch.static_paths():
        add(a,b,"static projection",extra=path)
    writes = sorted(k for k in branch.on if branch.by[k].op=="W")
    for w,r in sorted(branch.selected):
        support = {("select",w,r), ("decl-rf",w,r)} | branch.endpoints(r)
        if w.startswith("init:"):
            for v in writes:
                if branch.by[v].addr == branch.by[r].addr:
                    add(r,v,"initial read",extra=support)
        else:
            add(w,r,"read from",extra=support)
    while True:
        count = len(facts)
        for a,b in sorted(facts):
            for c in sorted(branch.on):
                if (b,c) in facts:
                    add(a,c,"transitive",((a,b),(b,c)))
            if branch.groups[a] != branch.groups[b]:
                # An external order fixes the order of both contiguous blocks.
                for x in sorted(branch.groups[a] & branch.on):
                    for y in sorted(branch.groups[b] & branch.on):
                        add(x,y,"block lift",((a,b),),(branch.membership[a],branch.membership[b]))
            for w,r in sorted(branch.selected):
                if w.startswith("init:"):
                    continue
                support = {("select",w,r),("decl-rf",w,r)} | branch.endpoints(w,r)
                if a == w and b != w and b in writes and branch.by[b].addr == branch.by[w].addr:
                    add(r,b,"from read",((a,b),),support)
                if b == r and a != w and a in writes and branch.by[a].addr == branch.by[w].addr:
                    add(a,w,"write serialization",((a,b),),support)
        if len(facts) == count:
            break
    return facts,stats


def extensions(branch, facts):
    """Explore legal prefixes, checking the chosen RF on each enabled read."""
    want = {r:w for w,r in branch.selected}
    pred = {k:{a for a,b in facts if b==k} for k in branch.on}
    def walk(seq, left, last):
        if not left:
            yield seq
            return
        allowed = left
        if seq and (remaining := branch.groups[seq[-1]] & left):
            allowed = remaining
        for k in sorted(allowed):
            e = branch.by[k]
            if pred[k] & left or (e.op=="R" and want[k] != last.get(e.addr,"init:"+e.addr)):
                continue
            new_last = last | {e.addr:k} if e.op=="W" else last
            yield from walk(seq + (k,), left - {k}, new_last)
    return walk((),branch.on,{})


def run(graph, prior=None):
    by = graph.validate()
    bank, models, counts = {}, set(), Counter()
    for env in valuations(graph):
        on = {k for k,e in by.items() if active(e,env)}
        reads = sorted(k for k in on if by[k].op=="R")
        options = [[(w,r) for w,end in sorted(set(graph.rf)) if end==r
                    and (w in on or w=="init:"+by[r].addr)] for r in reads]
        for choices in product(*options):
            picked = tuple(sorted(choices))
            key = (env,picked)
            branch = Branch(graph,env,picked)
            facts,stats = saturate(branch, (prior or {}).get(key))
            counts.update(stats)
            counts["branches"] += 1
            bank[key] = facts
            for seq in extensions(branch,facts):
                models.add((env,picked,seq))
    counts["expired_branches"] = len(set(prior or {})-bank.keys())
    return models,bank,counts


def explain(facts, goal):
    steps = {}
    def visit(pair):
        if pair not in steps:
            proof = facts[pair]
            parents = [visit(p) for p in proof.parents]
            steps[pair] = {"id":len(steps),"edge":list(pair),"rule":proof.rule,
                           "parents":parents,"premises":sorted(proof.local)}
        return steps[pair]["id"]
    visit(goal)
    return list(steps.values())
