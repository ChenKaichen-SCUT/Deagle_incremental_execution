"""Count per-content selectors at the frozen first query, without executing either model."""
import csv
import gzip
import hashlib
import io
import json
import struct
import sys
from collections import Counter
from pathlib import Path

from frozen import CASES, RESEARCH, blob, digest, require, save

GRAPH = {b"EDGE", b"GUARD", b"NODE", b"MEMBER", b"IN", b"OUT", b"CO"}


def read_model(repo, case, side):
    path = f"reports/evidence/si1b/{case}/native/{side}/audit/model.tsv.gz"
    packed = blob(repo, path)
    sets = {"B": set(), "Q": set()}
    occurrences, skipped, graph_rows = Counter(), Counter(), Counter()
    seal, query, boundary, targets = hashlib.sha256(), 0, None, []
    max_var = 0
    with gzip.GzipFile(fileobj=io.BytesIO(packed)) as lines:
        require(next(lines) == b"DEAGLE-D1\t1\n", "unexpected model format")
        for line in lines:
            f = line.rstrip(b"\n").split(b"\t")
            k = f[0]
            if k == b"C":
                require(boundary is None, "additional input after query boundary")
                scope = f[1].decode()
                occurrences[scope] += 1
                lits = set(map(int, f[2:]))
                require(all(l >= 2 or l in (-1, -2) for l in lits), "unrecognized wire literal")
                # D1 raw constants -1=true, -2=false. All others are 2*var + sign.
                if -1 in lits or any(l >= 2 and (l ^ 1) in lits for l in lits):
                    skipped[scope] += 1
                    continue
                lits.discard(-2)
                ordered = sorted(lits)
                if ordered:
                    max_var = max(max_var, ordered[-1] // 2)
                sets[scope].add(struct.pack(f"<{len(ordered)}I", *ordered))
            elif k in GRAPH:
                seal.update(line)
                graph_rows[k.decode()] += 1
                if k == b"EDGE":
                    graph_rows["edge_" + f[1].decode()] += 1
            elif k == b"QUERY":
                query += 1
            elif k == b"TARGET":
                targets.append(f[1].decode())
            elif k == b"N":
                require(boundary is None, "multiple incompatible boundaries")
                boundary = list(map(int, f[1:]))
    require(query == 1 and targets and boundary and max_var < boundary[0], "incomplete model")
    stats = {}
    for scope, keys in sets.items():
        stats[scope] = dict(occurrences=occurrences[scope], unique=len(keys),
                            duplicate_occurrences=occurrences[scope]-skipped[scope]-len(keys),
                            true_or_tautological=skipped[scope], empty=int(b"" in keys),
                            unit=sum(len(k) == 4 for k in keys),
                            unique_literal_words=sum(map(len, keys)) // 4)
    counts = dict(model=path, compressed_sha256=digest(packed), native_nvars=boundary[0],
                  native_assumptions=boundary[1:], targets=targets, scopes=stats,
                  installed_graph=dict(graph_rows), archived_graph_stream_sha256=seal.hexdigest(),
                  query_boundaries=query)
    return counts, sets


def registry_layout(layout, boolean_count, query_count, bool_words, query_words,
                    bool_empty, epochs, queries, native_assumptions):
    lit, cref, clause, watcher, vardata, watch_vec, lbool, activity, integer = layout
    guard_count = boolean_count + query_count + epochs + queries
    assume = guard_count + native_assumptions
    # Pre-simplification, one watch pair and one CRef per non-unit installed clause.
    # A guarded empty B is a permanent unit. Q clauses carry both their own selector and query guard.
    allocated = boolean_count + query_count - bool_empty
    allocator = (clause + 2 * watcher + cref) * allocated
    allocator += (bool_words + query_words + boolean_count - bool_empty + 2 * query_count) * lit
    # Count native arrays at logical length. Excludes capacity growth, decision heap and allocator padding.
    per_var = 2 * watch_vec + 2 + 2 * lbool + vardata + activity + 3 + lit
    byte_parts = dict(guarded_clauses_and_watches=allocator, selector_arrays=per_var * guard_count,
                      one_assumption_vector=assume * lit, six_level_limits_if_all_installed=6 * integer * assume,
                      proposed_registry_offsets_sizes_ids_flags=4 * integer * (boolean_count + query_count),
                      proposed_registry_payloads=(bool_words + query_words) * lit)
    return dict(registered_B=boolean_count, registered_Q=query_count, epoch_selectors=epochs,
                query_selectors=queries, assumptions=assume, bytes=byte_parts,
                modeled_subtotal_bytes=sum(byte_parts.values()))


def count_case(repo, case, layout):
    old, a = read_model(repo, case, "P0")
    new, b = read_model(repo, case, "P1")
    coords = json.loads(blob(repo, f"reports/evidence/si1b-review/{case}/wire-coordinates.json"))
    for side, data in (("P0", old), ("P1", new)):
        require(coords[side]["first_root_native_streams_equal"] and
                coords[side]["native_variable_count"] + 1 == data["native_nvars"], "coordinate mismatch")
    path = f"reports/evidence/si1b/{case}/join/direct-map.tsv.gz"
    raw = blob(repo, path)
    positive = {}
    images = set()
    for row in csv.DictReader(io.StringIO(gzip.decompress(raw).decode()), delimiter="\t"):
        x, y = int(row["old_variable"]), int(row["positive_image"])
        require(0 < x < old["native_nvars"] and 1 <= y // 2 < new["native_nvars"] and
                x not in positive and y // 2 not in images, "invalid signed direct map")
        positive[x] = y
        images.add(y // 2)
    # Only B may share in this estimate. Historical query-only renumberings never mediate sharing.
    if case == "fib-snapshot-11":
        alpha = json.loads(blob(repo, "reports/evidence/d42/encoding.json"))
        for side, values in (("P0", set(positive)), ("P1", images)):
            q = alpha[side]["alpha"]
            require(q["exact_all_scopes"] and not values.intersection(map(int, q["permutation"])),
                    "query-only bridge enters shared map")
    shared_count, shared_words = 0, 0
    for key in a["B"]:
        translated = []
        for (lit,) in struct.iter_unpack("<I", key):
            mapped = positive.get(lit // 2)
            if mapped is None:
                break
            translated.append(mapped ^ (lit & 1))
        else:
            mapped_key = struct.pack(f"<{len(translated)}I", *sorted(translated))
            if mapped_key in b["B"]:
                shared_count += 1
                shared_words += len(translated)
    def single(model):
        p, q = model["scopes"]["B"], model["scopes"]["Q"]
        return registry_layout(layout, p["unique"], q["unique"], p["unique_literal_words"],
                               q["unique_literal_words"], p["empty"], 1, 1, len(model["native_assumptions"]))
    p, q = old["scopes"], new["scopes"]
    def combined(shared, words, shared_empty):
        return registry_layout(layout, p["B"]["unique"] + q["B"]["unique"] - shared,
                               p["Q"]["unique"] + q["Q"]["unique"],
                               p["B"]["unique_literal_words"] + q["B"]["unique_literal_words"] - words,
                               p["Q"]["unique_literal_words"] + q["Q"]["unique_literal_words"],
                               p["B"]["empty"] + q["B"]["empty"] - shared_empty,
                               2, 2, len(new["native_assumptions"]))
    empty_shared = int(b"" in a["B"] and b"" in b["B"])
    union = combined(shared_count, shared_words, empty_shared)
    fresh = combined(empty_shared, 0, empty_shared)
    return dict(P0=old, P1=new, map_path=path, map_sha256=digest(raw), mapped_atoms=len(positive),
                certified_shared_B=shared_count, shared_B_literal_words=shared_words,
                distinct_local_graph_streams=len({old["archived_graph_stream_sha256"], new["archived_graph_stream_sha256"]}),
                P0_epoch_plan=single(old), P1_active_only=single(new), P1_union_with_diagnostic_map=union,
                P1_union_with_fresh_atoms=fresh)


if __name__ == "__main__":
    repo, probe, output = map(Path, sys.argv[1:])
    fields, = [s.split()[1:] for s in probe.read_text().splitlines() if s.startswith("LAYOUT ")]
    layout = list(map(int, fields))
    require(layout == [4, 4, 4, 8, 8, 16, 1, 8, 4], "update the ABI-based cost model")
    result = {}
    for case in CASES:
        result[case] = count_case(repo, case, layout)
        print(case, result[case]["P0_epoch_plan"]["assumptions"],
              result[case]["P1_union_with_diagnostic_map"]["assumptions"], flush=True)
    save(output, dict(research_sha=RESEARCH, layout_bytes=layout, cases=result))
