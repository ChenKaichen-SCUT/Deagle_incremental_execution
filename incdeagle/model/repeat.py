"""Stronger same-input replay check. These local-coordinate digests never enter a version delta."""
from functools import lru_cache

from .identity import digest


def phase_digest(document):
    pool = document["ireps"]

    @lru_cache(None)
    def intern(index):
        if index is None:
            return None
        n = pool[index]
        named = {k: intern(v) for k, v in n.get("named", {}).items() if k not in {"#source_location", "#end_location"}}
        return digest([n["id"], named, [intern(i) for i in n.get("sub", [])]])

    refs = {"guard", "condition", "lhs", "rhs", "full_lhs", "original_lhs", "code"}

    def row(raw):
        result = dict(raw)
        for k in refs.intersection(raw):
            result[k] = intern(raw[k])
        for k in ("arguments", "io_args"):
            if k in raw:
                result[k] = [intern(i) for i in raw[k]]
        return result

    normalized = {k: v for k, v in document.items() if k != "ireps"}
    for table in ("steps", "instructions", "oc_guards", "oc_edges", "thread_births"):
        if table in document:
            rows = [row(r) for r in document[table]]
            # Guard sets are native pointer-ordered. Edges form a multiset.
            normalized[table] = sorted(map(digest, rows)) if table in {"oc_guards", "oc_edges"} else rows
    return digest(normalized)
