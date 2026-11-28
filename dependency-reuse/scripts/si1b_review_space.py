"""Read-only common-coordinate and signed-injection checks for SI-1B-review."""
from collections import Counter, defaultdict
from contextlib import contextmanager
import csv
import gzip
import hashlib
import io
import json
import shutil
from pathlib import Path

from d43_project_support import check, digest, zipped
from si1a_census import fingerprint
from si1b_witness import verify

BASE = Path(__file__).resolve().parents[1]
EVIDENCE = BASE / "reports/evidence"
CASES = ("fib_updates_8", "circular-buffer", "airline_reservations_6", "fib-snapshot-11")
MATRIX = ("A", "B", "C")


def read(path):
    return json.loads(path.read_bytes())


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def rows(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as f:
        yield from csv.DictReader(f, delimiter="\t")


@contextmanager
def table(path, columns):
    with zipped(path) as gz, io.TextIOWrapper(gz, encoding="utf8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(columns.split())
        yield writer.writerow


@contextmanager
def jsonlines(path):
    with zipped(path) as gz:
        yield lambda obj: gz.write((json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode())


def extract(source, dest):
    with gzip.open(source, "rb") as f, dest.open("wb") as out:
        shutil.copyfileobj(f, out)


def authentic(path, index, key):
    row = index[key]
    check(path.stat().st_size == row["bytes"] and digest(path) == row["sha256"], "archive mismatch " + key)


def coordinates(case, side, tap, model, receipt, audit, cwd):
    """Compare permanent occurrences at their positions, including multiplicity; sort only unordered directories."""
    alpha = {}
    if case == "fib-snapshot-11":
        frozen = read(EVIDENCE / "d42/encoding.json")[side]["alpha"]
        check(frozen["exact_all_scopes"], "unverified query bridge")
        alpha = {int(k): v for k, v in frozen["permutation"].items()}
    check(set(alpha) == set(alpha.values()), "partial query permutation")
    def translate(lit):
        return 2 * alpha.get(lit // 2, lit // 2) + (lit & 1) if lit >= 2 else lit
    def scan(f, default):
        b, graph, gates_order = (hashlib.sha256() for _ in range(3))
        q, bindings, gates, count = Counter(), Counter(), Counter(), Counter()
        protected, interface = set(), set()
        boundary = None
        for line in f:
            k, _, rest = line.rstrip(b"\n").partition(b"\t")
            if k == b"C":
                scope, _, clause = rest.partition(b"\t")
                count[scope.decode()] += 1
                if scope == b"Q":
                    lits = map(int, clause.split())
                    q[tuple(sorted(map(translate, lits) if default else lits))] += 1
                else:
                    b.update(f"{count['B']+count['Q']+count['U']} ".encode() + line)
                    if alpha:
                        protected.update(n//2 for n in map(int, clause.split()) if n >= 2 and n//2 in alpha)
            elif k == b"A":
                bindings[line] += 1
                l = int(rest.rsplit(b"\t", 1)[1])
                if l >= 2 and l//2 in alpha:
                    protected.add(l//2)
            elif k == b"G":
                count["gates"] += 1
                gates_order.update(line)
                if alpha:
                    op, *xs = rest.split()
                    lits = list(map(int, xs))
                    gates[(op, *(map(translate, lits) if default else lits))] += 1
            elif k in {b"EDGE", b"GUARD", b"NODE", b"MEMBER", b"IN", b"OUT", b"CO"}:
                graph.update(line)
                count["installed_" + k.decode()] += 1
                p = rest.split(b"\t")
                literals = (p[3],p[6]) if k == b"EDGE" else p[-1:] if k == b"GUARD" else p[2:] if k == b"CO" else ()
                interface.update(v//2 for x in literals if (v := int(x)) >= 2)
            elif k == (b"QUERY" if default else b"N"):
                boundary = tuple(map(int, rest.split()))
                break
        check(boundary is not None and count["B"] and count["Q"], "incomplete native scope")
        return b.hexdigest(), graph.hexdigest(), q, bindings, gates, gates_order.hexdigest(), count, boundary, protected, interface

    with gzip.open(tap, "rb") as f, model.open("rb") as g:
        l, r = scan(f, True), scan(g, False)
    check(l[:5] == r[:5] and l[6:] == r[6:] and (bool(alpha) or l[5] == r[5]), "unaligned native input, gate, port or graph " + side + " fields " + str([i for i in range(len(l)) if l[i]!=r[i]]))
    check(not l[8] and not (alpha.keys() & l[9]) and not any(x//2 in alpha for x in l[7][1:]), "query helpers enter permanent coordinates")
    check(receipt["original"]["allocation_ranges"] == receipt["shadow"]["allocation_ranges"] and
          receipt["original"]["scope_streams"] == receipt["shadow"]["scope_streams"], "default shadow alias")
    check(fingerprint(model, cwd) == audit["models"], "SI manifest, including static declarations, differs from D4.3")
    info = dict(counts=l[6], signed_port_rows=sum(l[3].values()), boundary=l[7], query_permutation=alpha,
                permanent_occurrence_sha256=l[0], ordered_graph_sha256=l[1], query_multiset_equal=True,
                signed_port_multiset_equal=True, gate_multiset_equal=True, ordered_gates_equal=l[5] == r[5],
                first_root_model_sha256=audit["models"]["canonical_sha256"], quarantined_ids=sorted(alpha))
    return info, l[9], set(alpha)


def sign_inverse(mapping):
    inverse = {}
    for v,p in mapping.items():
        check(v > 0 and p >= 2 and p//2 not in inverse, "noninjective signed map")
        inverse[p//2] = 2*v+(p&1)
    return inverse


def build_maps(prod, si, tmp, out, sizes, interfaces, quarantine):
    a, reverse = {}, {}
    for item in rows(prod / "effective-map.tsv"):
        side, v, p = (int(item[k]) for k in ("side","variable","peer"))
        check(0 < v < sizes[side] and (p == -1 or 2 <= p < 2*sizes[1-side]), "map boundary")
        if p >= 2:
            (a,reverse)[side][v] = p
    check(sign_inverse(a) == reverse, "published A inverse differs")
    folder = tmp / "witness"
    for side in ("P0","P1"):
        d = folder / side
        d.mkdir(parents=True)
        blob = si / "native" / side / "shadow"
        extract(blob / "native.bin.gz", d / "native.bin")
        shutil.copyfile(blob / "seal.json", d / "seal.json")
    receipt = verify(folder, si / "source", si / "join")
    check(receipt == read(si / "audit/witness-audit.json"), "independent direct-key verifier changed")
    b, keys = {}, {}
    for item in rows(si / "join/direct-map.tsv.gz"):
        v,p,k = map(int, (item["old_variable"],item["positive_image"],item["witness_key"]))
        check(0 < v < sizes[0] and 2 <= p < sizes[1]*2 and v not in b, "B coordinates")
        b[v] = p
        keys[v] = k
    sign_inverse(b)
    for m in (a,b):
        check(not (m.keys() & quarantine[0] or sign_inverse(m).keys() & quarantine[1]), "mapped query coordinate")
    # Protect alternate literal aliases and the complete installed native interface, irrespective of the B recipe.
    for line in (prod / "delta/variables.tsv").open():
        side, var, _, role, *_ = line.split()
        if role in {"RF","Guard","CO","Interface","Theory"}:
            interfaces[int(side)].add(int(var))
    c, inv = a.copy(), reverse.copy()
    decisions = Counter()
    with table(out / "composition.tsv.gz", "old B_positive typed_key A_positive A_reverse_signed decision") as write:
        for v,p in sorted(b.items()):
            previous, owner = a.get(v,-1), inv.get(p//2,-1)
            if previous == p:
                decision = "already_identical"
            elif previous >= 2:
                decision = "forward_or_polarity_conflict"
            elif owner >= 2:
                decision = "reverse_target_occupied"
            elif v in interfaces[0] or p//2 in interfaces[1]:
                decision = "theory_port_or_alias"
            else:
                decision = "added_certified_ordinary"
                c[v] = p
                inv[p//2] = 2*v+(p&1)
            decisions[decision] += 1
            write([v,p,keys[v],previous,owner,decision])
    check(sign_inverse(c) == inv and a.items() <= c.items(), "C changed an old signed binding")
    return dict(A=a,B=b,C=c),keys,decisions
