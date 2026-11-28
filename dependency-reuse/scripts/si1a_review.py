"""Recompute SI-1A diagnosis and conditional cost bounds from frozen records. No solver invocation."""
import argparse
from collections import Counter
import csv
import gzip
import io
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess

from cases42 import load
from d42_events import unchanged
from run_stock import BASE, save, sha
from si1a_census import check, rows, write_tsv
from si1a_probe import BASELINE, ELF


def proof_cases(d, b, out, tmp, specs):
    src = BASE / "stable-identity/si1a_ancestors.cpp"
    exe = tmp / "si1a-ancestors"
    tmp.mkdir(parents=True, exist_ok=True)
    subprocess.run(["g++", "-O2", "-std=c++11", "-I", "src", "-I", "minisat-2.2.1", str(src),
                    "minisat-2.2.1/minisat/core/ProofStore.cc", "-o", str(exe)], cwd=BASE.parent, check=True)
    idx = json.loads((BASE / "reports/evidence/d43b/raw/files.json").read_text())["files"]
    d_index = json.loads((BASE / "reports/evidence/d43d/raw/files.json").read_text())["files"]
    counts, receipts = [], {}
    for case in specs:
        relative = "accepted/" + case + "/compact-audit/native/proof.bin"
        archive = b / relative
        digest = sha(archive)
        check(digest == idx[relative]["sha256"], "unbound audit DAG")
        exact = d / "exact" / case
        files = [exact / (n + ".tsv") for n in ("inputs42", "facts42", "catalog42")]
        check(all(sha(f) == d_index[str(f.relative_to(d))]["sha256"] for f in files), "unbound D leaf verdict")
        cmd = [exe, archive, *files]
        stream = subprocess.check_output(cmd)
        counter = Counter()
        exceptions = []
        for r in csv.DictReader(io.StringIO(stream.decode()), delimiter="\t"):
            mask = int(r["mask"])
            if r["permanent"] == "1":
                check(not mask & 16, "permanent result depends on scoped leaf")
                uncertain = bool(mask & 5)
                absent = bool(mask & 10)
                reason = "both" if uncertain and absent else "uncertified_only" if uncertain else "absent_only" if absent else "intact"
                counter[int(r["mapped"]), reason] += 1
                if case == "airline_reservations_6" and r["mapped"] == "1":
                    exceptions.append(dict(ordinal=int(r["ordinal"]), loss_mask=mask, category=reason))
        counts.extend((case, mapped, reason, counter[mapped, reason]) for mapped in (0, 1) for
                      reason in ("intact", "uncertified_only", "absent_only", "both"))
        dst = out / "proof" / (case + ".tsv.gz")
        dst.parent.mkdir(exist_ok=True)
        with dst.open("wb") as f, gzip.GzipFile(fileobj=f, filename="", mode="wb", mtime=0) as g:
            g.write(stream)
        receipts[case] = dict(audit_archive=relative, audit_sha256=digest, reference_tables={
            f.name: sha(f) for f in files}, masks_sha256=sha(dst), mapped_airline_examples=exceptions)
    write_tsv(out / "proof-dispositions.tsv", "case conclusion_mapped support_state permanent_births", counts)
    save(out / "proof-read-receipts.json", receipts)


def time_bounds(out):
    formal = BASE / "reports/evidence/d43e"
    reuse = {(r["case"], r["round"]): r for r in rows(formal / "runs.tsv")
             if r["mode"] == "compact-reuse" and r["side"] == "P1"}
    columns = ("case round reuse_P1_ns stock_P1_ns worker_ns residual_P1_ns cycle_residual_ns "
               "semantic_variables_models_ns structural_ns pure_search_gain_ns")
    data = []
    for p in rows(formal / "pairs.tsv"):
        r = reuse[p["case"], p["round"]]
        worker = int(r["worker_process_ns"])
        old, stock = int(p["reuse_P1_ns"]), int(p["stock_P1_ns"])
        check(old == int(r["wall_ns"]) and 0 < worker <= old, "bad paired duration")
        data.append((p["case"], p["round"], old, stock, worker, old-stock-worker,
                     int(p["reuse_cycle_ns"])-int(p["stock_cycle_ns"])-worker,
                     int(r["semantic_variables_models_ns"]), int(r["structural_refinement_ns"]),
                     int(p["search_gain_ns"])))
    write_tsv(out / "zero-worker-pairs.tsv", columns, data)
    medians = {}
    for case in load():
        cohort = [v for v in data if v[0] == case]
        check(len(cohort) == 3, "expected E's three pairs")
        medians[case] = {k: int(statistics.median(row[i] for row in cohort))
                         for i,k in enumerate(columns.split()) if i >= 2}
        medians[case]["observed_P1_gap_ns"] = int(statistics.median(v[2]-v[3] for v in cohort))
    save(out / "zero-worker-medians.json", medians)


def inventory(out, d, specs):
    origins = json.loads((out / "origins.json").read_text())
    fingerprints = json.loads((out / "frozen-model-fingerprints.json").read_text())
    allocation = list(rows(out / "allocation-sites.tsv"))
    pack, frozen = [], {}
    for name, spec in specs.items():
        root = BASE / "bench" / name
        files = spec["files_sha256"]
        check(all(sha(root/f) == h for f,h in files.items()), "frozen input bytes differ")
        leaf = "program.c" if "program.c" in spec["inputs"]["P0"] else "program.i"
        old, new = (root / spec["inputs"][side][leaf] for side in ("P0", "P1"))
        patch = root / "patch.diff"
        inherited = unchanged(old.read_bytes(), new.read_bytes(), patch.read_bytes())
        protected = [n for n in ("harness.c", "phi.json", "gamma.json", "task.yaml", "unreach-call.prp") if (root/n).is_file()]
        frozen[name] = dict(files=files, protected={f:sha(root/f) for f in protected}, target=spec["target"],
                            argv=spec["argv"], limits=spec["limits"], staged=spec["inputs"],
                            patch=dict(file="patch.diff", sha256=sha(patch), old=sha(old), new=sha(new),
                                       verified_unchanged_lines=len(inherited)),
                            role="historical_INCOMPLETE_UNWINDING" if name=="fib-snapshot-11" else "repair_SAT_to_UNSAT")
        native = d / "matrix" / name / "compact-reuse/P1/native"
        diag = json.loads((native / "compact-delta.json").read_text())["theory"]["occurrences"]
        index_kinds = ("RuleConfig", "PO", "APO", "RFBinding", "GuardBinding",
                       "EventSchema", "SameAddress", "BlockCertificate")
        for side in ("P0", "P1"):
            o = origins[name][side]
            c = fingerprints[name][side]["rows"]
            a = [r for r in allocation if (r["case"], r["side"], r["scope"]) == (name,side,"all")]
            physical_helpers = sum(int(r["atoms"]) for r in a if "bv_utils.cpp" in r["native_allocation_site"] or
                                   "equality.cpp" in r["native_allocation_site"] or "boolbv_index.cpp" in r["native_allocation_site"])
            check(all(any(sub in r["native_allocation_site"] for sub in
                          ("cnf.cpp", "bv_utils.cpp", "equality.cpp", "boolbv_index.cpp", "boolbv_map.cpp",
                           "prop_conv_solver.cpp")) for r in a), "unpriced allocation source")
            role_rows = c["A"] + c["G"] + physical_helpers + o["sizes"]["rf_port_rows"] + o["sizes"]["guard_port_rows"]
            sources = 24*c["S"] + 24*c["X"] + 16*c["V"] + 24*c["E"]
            entries = sum(count for key in index_kinds for status,count in diag[key].items() if status.startswith(side+"_"))
            # P1 keeps the full membership index. P0 persists actual compact UsedLeaf content only.
            n_clause = o["sizes"]["used_C" if side == "P0" else "permanent_C"]
            n_lits = o["sizes"]["used_C_literals" if side == "P0" else "permanent_C_literals"]
            if side == "P0":
                nt = sum(origins[name]["support"]["theory"].values())
            else:
                nt = entries
            template_atoms = physical_helpers + sum(int(r["atoms"]) for r in a if "/cnf.cpp" in r["native_allocation_site"])
            hits = sum(o["cache"][k] for k in ("BOOL_H","BV_H"))
            typed = n_clause*12 + n_lits*4 + nt*24
            port_bytes = role_rows*32
            cache_bytes = template_atoms*12 + hits*8
            pack.append((name,side,c["S"],c["X"],c["V"],c["E"],c["A"],c["G"],physical_helpers,
                         role_rows,port_bytes,sources,n_clause,n_lits,nt,typed,template_atoms,hits,cache_bytes,
                         port_bytes+sources+typed+cache_bytes))
    write_tsv(out / "wire-size-scenarios.tsv",
              "case side site_rows context_rows value_rows event_rows named_port_rows gate_rows "
              "helper_free_roles port_role_rows port_wire_B source_context_wire_B indexed_clauses "
              "indexed_literals indexed_theory_rows support_wire_B template_rows cache_hit_rows cache_wire_B subtotal_B", pack)
    save(out / "frozen-inputs.json", frozen)


def environment(out, build_path):
    frozen = json.loads((BASE / "configs/build.json").read_text())
    info = json.loads(build_path.read_text())
    stock = Path(frozen["binary_path"])
    check(info["production"] == ELF and sha(stock) == frozen["binary_sha256"], "frozen binary mismatch")
    binary = build_path.parent / "si1a-deagle"
    check(sha(binary) == info["observer"], "observer changed")
    check(all(json.loads(p.read_text())["binary_sha256"] == info["observer"] for p in
              (out / "probe").glob("*.json")), "mixed diagnostic binaries")
    save(out / "probe-build.json", info)
    host = dict(base_commit=BASELINE, linux=platform.release(), distro=Path("/etc/os-release").read_text(),
                python=platform.python_version(), compiler=subprocess.check_output(["g++","--version"],text=True).splitlines()[0],
                affinity_available=sorted(os.sched_getaffinity(0)), model_cpu=0,
                cpu=next(x.split(": ",1)[1] for x in Path("/proc/cpuinfo").read_text().splitlines() if x.startswith("model name")),
                mem_total_kib=int(Path("/proc/meminfo").read_text().splitlines()[0].split()[1]),
                stock_sha256=sha(stock), production_sha256=ELF, probe_sha256=info["observer"],
                old_library_version="D43DNS2", source_guide_sha256="dcbd127ed092536ba94f0ee8d88538811aefafc4cab253b11fb2988bcfbd1ec5")
    save(out / "environment.json",host)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("restored_D", type=Path)
    p.add_argument("restored_B", type=Path, help="contains accepted/<case>/compact-audit/native/proof.bin")
    p.add_argument("evidence", type=Path)
    p.add_argument("scratch", type=Path)
    p.add_argument("--observer-build", type=Path, help="optional fresh diagnostic build.json on original host")
    args = p.parse_args()
    specs = load()
    time_bounds(args.evidence)
    inventory(args.evidence, args.restored_D, specs)
    proof_cases(args.restored_D, args.restored_B, args.evidence, args.scratch, specs)
    if args.observer_build:
        environment(args.evidence,args.observer_build)
