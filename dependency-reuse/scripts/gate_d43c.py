"""Compose the C gate from checked native, model, mutation and inherited B evidence."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from audit_d43b import Library, seals
from cases42 import load
from d43_project_support import check, digest, save
from run_d42 import compare
from run_stock import BASE

MODES = ("identity", "unsigned", "signed")
FAULTS = """
eliminated_B_ancestor explicit_root_unit successful_minimization second_same_slot_UsedLeaf
stale_tag_after_eviction query_forged_permanent indirect_unknown_forged_permanent
second_same_slot_theory_UsedLeaf forged_discharge_all_literal_streams_agree conditionless_PO
conditionless_APO opaque_CO_certified missing_source_certified queue_reason_mixed
binding_native_polarity boundary_proofID_mixed dedup_overwrote_first_ticket stale_queue_ticket
omitted_DirtyT omitted_DirtyB wrong_schema wrong_capacity incomplete_footer truncated_archive
duplicate_independent_slot false_unchanged_RF false_unchanged_Guard false_unchanged_Block
false_unchanged_Direction false_unchanged_SameAddress false_complete_RF_domain incompatible_ABI incompatible_memory_model
incompatible_rule_version not_one_to_one wrong_known_polarity lost_overflow_B lost_overflow_T
scope_disposition_reclassified tampered_compact_payload tag_from_previous_RF_branch
""".split()
ZERO = ("SupportStore_instances", "proof_nodes", "proof_parent_edges", "duplicate_condition_nodes")


def read(path):
    return json.loads(path.read_bytes())


def table(path, columns, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def gate(captures, old, out):
    audits = read(captures / "audit/audit.json")
    controls = read(captures / "permutations/controls.json")
    spec = load()
    check([row["case"] for row in audits] == list(spec) and set(controls) == set(spec), "case denominator")
    checked, summary = [], []
    totals, inherited = Counter(), Counter()
    labels = ("boundaries", "propagation", "conflict", "theory_units", "immediate_RF", "immediate_guard",
              "RF_recheck", "guard_recheck", "reverse_RF", "exact", "unknown", "queued", "duplicates", "discarded")
    b_evidence = BASE / "reports/evidence/d43b"
    for row in audits:
        case = row["case"]
        counts = Counter(row["boundaries"])
        prior = read(b_evidence / "cases" / case / "audit.json")
        check(row["same_full_Audit_except_three_clocks"] and row["same_dense_and_scoped"] and
              row["same_native_trace"] and row["properties"]["cold_trajectory_checked"], "B/C audit anchor")
        check(counts["boundaries"] == counts["certified"] + counts["unknown"] ==
              counts["propagation"] + counts["conflict"] + counts["co_definitions"], "boundary denominator")
        check(counts["exact"] == counts["certified"] and counts["queued"] ==
              counts["propagation"] + counts["discarded"], "boundary tag or queue")
        check(prior["birth_check"] == row["inherited_births"] and prior["counts"] == row["inherited_actual_leaves"]
              and prior["birth_check"]["equal_tags"] == row["confirmed_born"]
              and prior["permanent_union_missing"] == prior["candidate_subset_violations"] == 0, "birth or leaf gate")
        check(all(prior["stats"][key] == 0 for key in ZERO), "production support graph present")
        inherited.update(births=row["confirmed_born"], exact=sum(prior["exact"].values()),
                         eligible=sum(prior["eligible"].values()), mixed=prior["eligible"].get("M", 0))
        totals.update(counts)
        checked.append(dict(case=case, **{k:counts[k] for k in labels}))
        library = Library(old / case / "compact/native/dense.bin")
        ordinals = [i for i, flags, *rest in library.births() if not flags & 12]
        contexts = read(captures / "independent/faults/positive-contexts.json")[case]
        check(contexts["passed_modes"] == len(MODES), "configuration controls")
        for label in MODES:
            ctrl = controls[case][label]
            record = captures / "permutations" / case / label / "selected.tsv"
            actual = [int(i) for i in record.read_text().splitlines()[1:]]
            check(actual == ordinals[:512] and digest(record) == ctrl["selection_sha256"], "old ordinal cap")
            check(ctrl["eligible"] == len(ordinals) and ctrl["selected_under_cap"] == len(actual)
                  and sum(ctrl["rejected"].values()) + len(ordinals) == row["confirmed_born"], "model disposition")
            check(ctrl["old_directory_unchanged"] and ctrl["DirtyB"] == ctrl["DirtyT"] == 0
                  and ctrl["theory_declarations"] == len(library.t)
                  and ctrl["original_occurrences"] == len(library.b), "controlled registry or dirty mask")
            check(label != "signed" or ctrl["negative_images"] > 0, "signed control was unsigned")
            summary.append(dict(case=case, mode=label, variables=ctrl["native_variables"], events=ctrl["events"],
                                clauses=ctrl["original_occurrences"], declarations=ctrl["theory_declarations"],
                                DirtyB=ctrl["DirtyB"], DirtyT=ctrl["DirtyT"], negative_images=ctrl["negative_images"],
                                eligible=len(ordinals), selected=len(actual), query=ctrl["rejected"].get("query", 0),
                                unknown=ctrl["rejected"].get("unknown", 0)))
    mode_totals = {}
    for label in MODES:
        records = [r for r in summary if r["mode"] == label]
        mode_totals[label] = {key:sum(r[key] for r in records) for key in ("eligible", "selected", "query", "unknown")}
        repairs = [r for r in records if r["case"] != "fib-snapshot-11"]
        check(mode_totals[label]["eligible"] == 97901 and sum(r["eligible"] for r in repairs) == 43295,
              "controlled permanent denominator")
        mode_totals[label].update(repair_eligible=43295, repair_selected=sum(r["selected"] for r in repairs))
    check(inherited == dict(births=152817, exact=388, eligible=311, mixed=264), "B denominators changed")

    rejected = read(captures / "independent/rejections.json")
    fixtures = read(captures / "independent/fixtures.json")
    check(set(rejected) == set(FAULTS) and all(x["disposition"] == "REJECTED" and x["observed"] and x["witness"]
                                               for x in rejected.values()), "mutation escaped or lacks evidence")
    check(fixtures["dynamic-CO"]["unknown"] == fixtures["missing-source"]["unknown"] == 1
          and fixtures["empty-PO-APO"]["certified"] == fixtures["immediate-guard"]["certified"] == 1
          and fixtures["branch-edges"]["backtrack_in_out_zero"], "missing rare boundary controls")
    legacy = captures / "legacy/results"
    regression = {k:len(read(legacy / k / "results.json")) for k in ("d4", "triplets", "libraries", "light")}
    check(regression == dict(d4=27, triplets=31, libraries=6, light=77)
          and "root UNSAT verified" in (legacy / "imports.txt").read_text()
          and "unknown role rejected" in (legacy / "structure.txt").read_text(), "legacy regression suite")
    default = captures / "canary/fib_updates_8/compact"
    seals(default)
    compare(old / "fib_updates_8/off", default, True)
    check(digest(default / "native/dense.bin") == digest(old / "fib_updates_8/compact/native/dense.bin"),
          "production canary changed the B archive")
    stats = {k:int(v) for k,v in (s.split() for s in (default / "native/dense.bin.stats").read_text().splitlines())}
    check(all(stats[key] == 0 for key in ZERO) and not list(default.rglob("*.cert")), "production sidecar/graph")
    out.mkdir(parents=True, exist_ok=True)
    table(out / "native-boundaries.tsv", ["case", *labels], checked)
    table(out / "model-controls.tsv", list(summary[0]), summary)
    table(out / "negative-controls.tsv", ["mutation", "observed"], [
        dict(mutation=k, observed=v["observed"]) for k,v in rejected.items()])
    save(out / "gate.json", dict(gate="CORRECTNESS_GATE_PASSED", boundaries=totals, B_evidence=inherited,
         missing_exportable_leaves=0, false_admissions=0, controlled_models=mode_totals,
         rejected_injections=len(rejected), native_fixture_contexts=len(fixtures), legacy_result_entries=regression,
         default_canary={k:stats[k] for k in ZERO}, real_P1_runs=0,
         per_candidate_SAT_RUP_Closure_reproofs=0))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("captures", "B_matrix", "out"):
        p.add_argument(name, type=Path)
    args = p.parse_args()
    gate(args.captures, args.B_matrix, args.out)
