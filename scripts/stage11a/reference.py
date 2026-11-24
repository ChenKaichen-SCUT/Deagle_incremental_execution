"""Strict, finite SC oracle. No Closure, SAT, or candidate-rule imports."""
from dataclasses import asdict, dataclass
from itertools import permutations, product
import re


@dataclass(frozen=True)
class Event:
    key: str
    thread: str
    op: str
    addr: str
    guard: str = "1"
    typ: str = "int32"


@dataclass(frozen=True)
class Graph:
    events: tuple
    po: tuple = ()
    apo: tuple = ()  # Each directed edge also puts its endpoints in one atomic section.
    rf: tuple = ()   # Declared (source, read) choices, including explicit init:<addr>.
    name: str = ""

    def document(self):
        return asdict(self)

    def validate(self):
        by = {e.key: e for e in self.events}
        if len(by) != len(self.events) or any(k.startswith("init:") for k in by):
            raise ValueError("ambiguous_event_identity")
        for e in self.events:
            if (e.op not in ("W", "R", "N") or (e.op != "N" and not e.addr)
                    or not re.fullmatch(r"(?:[01]|!?[A-Za-z_][A-Za-z_0-9]*)",e.guard)):
                raise ValueError("unknown_event_or_guard")
        for a, b in self.po + self.apo:
            if a not in by or b not in by:
                raise ValueError("unbound_order_endpoint")
        for a, b in self.apo:
            if by[a].thread != by[b].thread:
                raise ValueError("atomic_crosses_threads")
        for w, r in self.rf:
            if r not in by or by[r].op != "R":
                raise ValueError("invalid_rf_read")
            if w == "init:" + by[r].addr:
                continue
            if w not in by or (by[w].op, by[w].addr, by[w].typ) != ("W", by[r].addr, by[r].typ):
                raise ValueError("invalid_rf_source")
        return by


def valuations(graph):
    names = sorted({e.guard.lstrip("!") for e in graph.events} - {"0", "1"})
    return [tuple(zip(names, values)) for values in product((False, True), repeat=len(names))]


def active(event, assignment):
    g = event.guard
    env = dict(assignment)
    if g in ("0", "1"):
        return g == "1"
    return not env[g[1:]] if g.startswith("!") else env[g]


def strict_models(graph):
    """Enumerate every order; derive the unique latest write by scanning backwards.

    Static PO/APO paths project through disabled events. APO components describe
    contiguous sections. Reads distinguish sources, including equal-valued writes.
    """
    by = graph.validate()
    orders = set(graph.po + graph.apo)
    blocks = [{e} for e in by]
    for a, b in graph.apo:
        touched = [group for group in blocks if a in group or b in group]
        blocks = [group for group in blocks if group not in touched] + [set.union(*touched)]
    # Warshall over static endpoints, including disabled events.
    for mid in by:
        left = [a for a, b in orders if b == mid]
        right = [b for a, b in orders if a == mid]
        orders.update((a, b) for a in left for b in right)
    result = set()
    for env in valuations(graph):
        on = {k for k,e in by.items() if active(e, env)}
        for seq in permutations(sorted(on)):
            pos = {e: i for i, e in enumerate(seq)}
            if any(pos[a] >= pos[b] for a,b in orders if a in on and b in on):
                continue
            spans = [[pos[e] for e in group & on] for group in blocks]
            if any(max(s)-min(s)+1 != len(s) for s in spans if s):
                continue
            chosen = []
            for i,r in enumerate(seq):
                if by[r].op != "R":
                    continue
                source = next((w for w in reversed(seq[:i]) if by[w].op == "W"
                               and by[w].addr == by[r].addr), "init:"+by[r].addr)
                if (source,r) not in graph.rf:
                    break
                chosen.append((source,r))
            else:
                result.add((env, tuple(sorted(chosen)), seq))
    return result
