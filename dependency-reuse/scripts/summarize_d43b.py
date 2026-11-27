"""Tabulate every P0 run, scope disposition, UsedLeaf count, and predeclared cost contrast."""
import argparse
import csv
import gzip
import json
from collections import Counter
from pathlib import Path
from d43b_dense import CASES
from d43_project_support import check, save
from d43_review import write_tsv
from run_d43b import MODES, DIAGNOSTICS


def load(path):
    return json.loads(path.read_bytes())


def summarize(matrix, audit, offline, output):
    output.mkdir(parents=True, exist_ok=True)
    costs, contrasts, leaves, retention, footprint, searches = [], [], [], [], [], []
    native = load(audit / "audit.json")
    catalogues = {r["case"]: r for r in load(offline / "dense-preflight.json")}
    totals = Counter()
    for case, a in zip(CASES, native, strict=True):
        check(a["case"] == case, "case order")
        times = {}
        for arm in (*MODES, "off-default", *DIAGNOSTICS):
            row = load(matrix / case / arm / "cost.json")
            times[arm] = row["total_ns"]
            costs.append([case, arm, row["result"], *(row[k] for k in
                ("process_ns", "seal_ns", "total_ns", "rss_kib", "search_ns", "record_bytes", "library_bytes")),
                row["files"].get("model.tsv", {}).get("bytes", (matrix/case/arm/"native/model.tsv").stat().st_size
                    if (matrix/case/arm/"native/model.tsv").exists() else 0)])
            for i, q in enumerate(row["search"], 1):
                searches.append([case, arm, i, *q.values()])
        quality = times["light-quality"] - times["light-no-quality"]
        legacy = times["light-no-quality"] - times["light-opaque"]
        dense = times["compact"] - times["compact-opaque"]
        opaque_diff = times["light-opaque"] - times["compact-opaque"]
        overall = times["light-quality"] - times["compact"]
        check(overall == quality + legacy - dense + opaque_diff, "inconsistent cost attribution")
        contrasts.append([case, times["compact"] - times["off"], times["compact"] - times["off-default"],
                          quality, legacy, dense, legacy-dense, opaque_diff, overall])
        s = a["stats"]
        footprint.append([case, *s.values()])
        for i, d in enumerate(("B", "T")):
            x = a["counts"]
            reg, obs, perm = (x.get(k + "_" + d, 0) for k in ("registered", "observed", "permanent_support"))
            check(0 <= perm <= obs <= reg, "UsedLeaf order")
            leaves.append([case, d, reg, obs, perm, reg-obs, obs-perm, x.get("dirty_leaves_" + d, 0),
                           a["dirty_slots"][i], a["registered_groups"][i], a["overflow_groups"][i],
                           catalogues[case]["expanded_groups"][i], catalogues[case]["overflow_expanded"][i],
                           ((s["original_occurrences"] if d=="B" else s["registered_theory"])+7)//8])
        classes = Counter()
        with gzip.open(audit/case/"birth-check.tsv.gz", "rt") as f:
            for b in csv.DictReader(f, delimiter="\t"):
                classes[b["class"]] += 1
        m = catalogues[case]["results"]
        for fam in ("B", "M", "T", "QUERY", "UNKNOWN"):
            exact = a["exact"].get(fam, 0)
            retained = a["eligible"].get(fam, 0)
            n = classes[fam]
            audit_bound = m["U_audit"].get("dense_"+fam, 0)
            all_bound = m["U_all"].get("dense_"+fam, 0)
            check(all_bound <= retained <= audit_bound, "retention interval")
            retention.append([case, fam, n, exact, audit_bound, retained, all_bound, exact-retained,
                              a["previously_hit"].get(fam, 0), m["expanded"].get("group_"+fam,0),
                              m["expanded"].get("dense_"+fam,0)])
            totals[fam+"_births"] += n
            totals[fam+"_eligible"] += retained
        check(classes["QUERY"]+classes["UNKNOWN"]==s["scoped_dispositions"] and
              s["births"]==sum(classes.values()), "production scope partition")
        for kind in ("all_births", "equal_tags", "superset_tags"):
            totals[kind] += a["birth_check"][kind] if kind in a["birth_check"] else 0
    write_tsv(output/"runs.tsv", ["case","mode","property","process_ns","seal_ns","inclusive_ns","peak_rss_kib",
        "native_search_ns","record_bytes","sealed_library_bytes","model_bytes"], costs)
    write_tsv(output/"search.tsv", ["case","mode","query",*q.keys()], searches)
    write_tsv(output/"cost-contrasts.tsv", ["case","compact_minus_off_ns","compact_minus_default_ns",
        "quality_on_minus_off_light_ns","theory_on_minus_opaque_light_ns","theory_on_minus_opaque_dense_ns",
        "theory_difference_ns","opaque_backend_difference_ns","light_quality_minus_compact_ns"], contrasts)
    write_tsv(output/"usedleaf.tsv", ["case","domain","registered_permanent","observed","permanent_support",
        "unobserved","observed_outside_permanent_union","dirty_observed","dirty_slots","registered_groups",
        "overflow_groups","expanded_groups","expanded_overflow","bitmap_bytes"], leaves)
    write_tsv(output/"retention.tsv", ["case","class","actual_births","exact_eligible","U_audit","U_actual",
        "U_all","lost_same_group","previous_D42_hits","expanded_logical","expanded_dense"], retention)
    write_tsv(output/"objects.tsv", ["case",*s.keys()], footprint)
    save(output/"totals.json", dict(totals))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for k in ("matrix", "audit", "preflight", "output"):
        p.add_argument(k, type=Path)
    a = p.parse_args()
    summarize(a.matrix, a.audit, a.preflight, a.output)
