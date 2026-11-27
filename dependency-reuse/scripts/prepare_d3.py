"""Bind local native graph IDs to exact D1 declarations before joint invalidation."""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
from urllib.parse import unquote

from prepare_d2 import prepare
from run_stock import BASE


def facts(manifest, delta, output):
    nodes, names, directions, members = {}, {}, set(), defaultdict(set)
    receipt=[]
    with gzip.open(manifest, "rt") as stream:
        for line in stream:
            tag = line.partition("\t")[0]
            if tag in {"NODE","IN","OUT","MEMBER","EDGE","GUARD"}:
                receipt.append(line)
            if tag not in {"NODE", "IN", "OUT", "MEMBER"}:
                continue
            fields = line.rstrip("\n").split("\t")[1:]
            if tag == "NODE":
                index, name, address, read, write, parent = fields
                i = int(index)
                name = unquote(name)
                if name in names or i in nodes:
                    raise ValueError("ambiguous native node numbering")
                nodes[i] = int(parent), int(address), int(read == "r"), int(write == "w")
                names[name] = i
            else:
                a, b = map(int, fields)
                if tag == "MEMBER":
                    members[a].add(b)
                else:
                    directions.add(("I" if tag == "IN" else "O", a, b))

    def root(i):
        seen = set()
        while nodes[i][0] != i:
            if i in seen:
                raise ValueError("cyclic native block parent")
            seen.add(i)
            i = nodes[i][0]
        return i

    declarations = {}
    with gzip.open(delta / "declarations.jsonl.gz", "rt") as stream:
        for line in stream:
            side, kind, local, _, key, state, why = json.loads(line)
            if side != 0:
                continue
            if kind == "RuleConfig":
                fact = (0, -1, -1, -1)
            elif kind in ("PO", "APO"):
                a, b = local
                fact = (1 if kind == "PO" else 2, names[a], names[b], -1)
            elif kind == "RFBinding":
                a, b, lit = local
                fact = (3, names[a], names[b], int(lit))
            elif kind == "GuardBinding":
                a, lit = local
                fact = (4, names[a], -1, int(lit))
            elif kind == "EventSchema":
                fact = (5, names[local], -1, -1)
            elif kind == "SameAddress":
                a, b = sorted(map(int, local))
                fact = (6, a, b, -1)
            elif kind == "BlockCertificate":
                ids = set(map(int, local))
                roots = {root(i) for i in ids}
                if len(roots) != 1 or members[next(iter(roots))] != ids:
                    raise ValueError("certificate differs from installed block")
                fact = (7, roots.pop(), -1, -1)
            else:
                continue
            status = {"matched": "M", "retired": "C", "unknown": "U"}[state]
            if status == "M" and not key:
                raise ValueError("matched declaration lacks a semantic identity")
            previous = declarations.setdefault(fact, status)
            if previous != status:
                declarations[fact] = "U"
    with output.open("x") as out:
        for line in receipt:out.write("G\t"+line)
        for i, (_, addr, r, w) in sorted(nodes.items()):
            print("N", i, root(i), addr, r, w, file=out)
        for row in sorted(directions):
            print(*row, file=out)
        for row, state in sorted(declarations.items()):
            print("D", *row, state, file=out)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("case")
    p.add_argument("output", type=Path)
    p.add_argument("--delta", type=Path)
    p.add_argument("--manifest", type=Path)
    a = p.parse_args()
    baseline = BASE / "reports/evidence/d1"
    pair = a.delta or baseline / "pairs" / a.case
    native = a.manifest or baseline / "runs/record" / a.case / "P0/native.tsv.gz"
    prepare(a.case, a.output, pair=pair, native=native)
    facts(native, pair, a.output / "declarations.txt")
