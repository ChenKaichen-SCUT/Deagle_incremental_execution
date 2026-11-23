"""Full-version provenance and conservative comparisons, with no transfer into a solver."""
import json
from collections import defaultdict

from .identity import digest, file_sha, read


def manifest(directory, case, gamma, phi, lock, gcc):
    calls = [json.loads(line) for line in (directory / "cpp.jsonl").read_text().splitlines()]
    if not calls or any(c["returncode"] for c in calls) or not any(c["unit"] == "harness.c" for c in calls):
        raise ValueError("Missing successful preprocessing of the actual translation unit")
    files, calls_stable = {}, []
    for c in calls:
        for name, sha in c["files"].items():
            if files.setdefault(name, sha) != sha:
                raise ValueError("Dependency changed during preprocessing: " + name)
        calls_stable.append({key: c[key] for key in ("argv", "unit", "output_sha256")})
    sources = {n: file_sha(directory / n) for n in ("program.c", "harness.c")}
    if any(files.get(k) != v for k, v in sources.items()):
        raise ValueError("Preprocessor did not read both staged input files")
    headers = {k: v for k, v in files.items() if k not in sources}
    context = {"schema": 1, "toolchain": lock, "preprocessor": gcc,
               "cpp_flags": sorted({tuple(c["argv"][:-1]) for c in calls}),
               "headers_and_builtin_inputs": headers, "architecture": gamma["semantics"]["target_bits"],
               "layout": read(directory / "goto.json")["layout"],
               "harness": sources["harness.c"], "property": phi, "gamma": gamma,
               "limits": gamma["limits"], "backend": gamma["semantics"]["backend"]}
    result = {"schema": 1, "case": case.name, "source_sha256": sources, "headers": headers,
              "preprocessing": calls_stable, "context": context, "context_sha256": digest(context)}
    result["version_sha256"] = digest(result)
    return result


def compare_mapping(left, right):
    left_ids, right_ids = set(left), set(right)
    overlap = left_ids & right_ids
    return {"matched": sorted(k for k in overlap if left[k]["unique"] and right[k]["unique"]),
            "rejected": sorted(k for k in overlap if not (left[k]["unique"] and right[k]["unique"])),
            "old_only": sorted(left_ids - right_ids), "new_only": sorted(right_ids - left_ids)}


def delta(old, new, before, after):
    mapping = {k: compare_mapping(old["mappings"][k], new["mappings"][k]) for k in ("sources", "instructions")}
    context_changes = sorted(k for k in before["context"] if digest(before["context"][k]) != digest(after["context"][k]))
    groups = []
    for m in (old, new):
        group = defaultdict(list)
        for e in m["events"]:
            group[e["id"]].append(e)
        groups.append(group)
    left, right = groups
    added, removed, changed, retained = [], [], [], []
    affected_threads, buckets, tainted = set(), set(), set()

    def affected(row):
        if row["bucket"]:
            buckets.add(row["bucket"])
        affected_threads.add(row["thread"])
        tainted.add("event:" + row["id"])

    for key in sorted(set(left) | set(right)):
        a, b = left.get(key, []), right.get(key, [])
        if len(a) == len(b) == 1 and a[0]["identity_unique"] and b[0]["identity_unique"]:
            l, r = a[0], b[0]
            reasons = [k for k in r["semantic"] if l["semantic"][k] != r["semantic"][k]]
            if not (l["comparable"] and r["comparable"]):
                reasons.append("unresolved_semantic_dependency")
            if context_changes:
                reasons.append("configuration_dependency")
            if reasons:
                comparison = "semantic_difference" if l["fingerprint"] != r["fingerprint"] else "unconfirmed"
                changed.append({"id": key, "old_step": l["native_step"], "new_step": r["native_step"],
                                "comparison": comparison, "reasons": reasons})
                affected(l)
                affected(r)
            else:
                retained.append(key)
        else:
            for rows, out in ((a, removed), (b, added)):
                for row in rows:
                    out.append({"id": key, "native_step": row["native_step"],
                                "reason": "ambiguous_identity" if not row["identity_unique"] or len(rows) > 1 else "unmatched"})
                    affected(row)

    # Decompose the two actual constraint multisets; never match ambiguous fragments.
    groups = []
    for m in (old, new):
        group = defaultdict(list)
        for i, f in enumerate(m["fragments"]):
            group[f["fingerprint"]].append(i)
        groups.append(group)
    gone, created, same = [], [], []
    for key in sorted(set(groups[0]) | set(groups[1])):
        left_indices, right_indices = groups[0].get(key, []), groups[1].get(key, [])
        valid_left = [i for i in left_indices if old["fragments"][i]["comparable"]]
        valid_right = [i for i in right_indices if new["fragments"][i]["comparable"]]
        n = 0 if context_changes else min(len(valid_left), len(valid_right))
        if n:
            same.append({"fingerprint": key, "count": n})
        gone.extend(sorted(set(left_indices) - set(valid_left[:n])))
        created.extend(sorted(set(right_indices) - set(valid_right[:n])))
    for model, indices in ((old, gone), (new, created)):
        for i in indices:
            f = model["fragments"][i]
            affected_threads.update(f["threads"])
            buckets.update(f["buckets"])
            if f["kind"] == "assignment":
                tainted.add("definition:" + f["owner"])
                lhs = model["typed_nodes"].get(f["typed_expression"]["lhs"], {})
                if "symbol" in lhs:
                    tainted.add(lhs["symbol"])
    # Separately expose identical expressions downstream of a changed definition.
    # This is diagnostic provenance, never a permission to replay the expression.
    expanded = True
    while expanded:
        n = len(tainted)
        for f in new["fragments"]:
            if f["kind"] == "assignment" and tainted.intersection(f["dependencies"]):
                lhs = new["typed_nodes"].get(f["typed_expression"]["lhs"], {})
                if "symbol" in lhs:
                    tainted.add(lhs["symbol"])
        for e in new["events"]:
            if tainted.intersection(e["dependencies"]):
                tainted.add("event:" + e["id"])
        expanded = n != len(tainted)
    downstream = [e for e in new["events"] if "event:" + e["id"] in tainted]
    for e in downstream:
        affected(e)
    scoped = sorted({f["fingerprint"] for f in new["fragments"] if tainted.intersection(f["dependencies"])})
    reasons = []
    if any(v["rejected"] for v in mapping.values()):
        reasons.append("ambiguous source or lowered instruction")
    if any(not e["comparable"] for m in (old, new) for e in m["events"]):
        reasons.append("unresolved event context, value or ordering dependency")
    if context_changes:
        reasons.append("manifest dependencies changed")
    if tainted:
        reasons.append("changed or unresolved event/definition dependencies")
    return {"schema": 1, "old_version": before["version_sha256"], "candidate_version": after["version_sha256"],
            "events_added": added, "events_removed": removed, "events_changed": changed, "events_retained": retained,
            "constraints_added": sorted(created), "constraints_removed": sorted(gone), "constraints_retained": same,
            "affected_threads": sorted(affected_threads), "affected_address_buckets": sorted(buckets),
            "source_mapping": mapping,
            "source_mapping_summary": {group: {k: len(seq) for k, seq in entry.items()} for group, entry in mapping.items()},
            "analysis_changes": {"configuration": context_changes, "changed_sources": sorted(
                k for k in before["source_sha256"] if before["source_sha256"][k] != after["source_sha256"][k]),
                "old_counts": old["counts"], "new_counts": new["counts"],
                "dependency_affected_events": sorted({e["id"] for e in downstream}),
                "dependency_affected_fragments": scoped,
                "scope": "observed bounded full models; upstream alias/dirty summaries are not certified for reuse"},
            "checkpoint_used": False, "invalidation_reasons": reasons, "fallback_reason": "stage3_full_only"}
