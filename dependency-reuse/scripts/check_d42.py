"""Verify a D4.2 review, including the arithmetic and optionally every raw file."""
import argparse
import csv
import json
from math import isclose
from pathlib import Path
from statistics import median

from d4_archive import read as verify_archive
from diff_d1 import digest
from run_stock import BASE


def read(path):
    return json.loads(path.read_text())


def paired(root, cases):
    with (root / "performance.tsv").open() as f:
        observations = [r for r in csv.DictReader(f, delimiter="\t") if r["phase"] == "paired"]
    by_key = {(r["case"], int(r["round"]), r["mode"], r["side"]): r for r in observations}
    assert len(by_key) == len(observations) == len(cases) * 3 * 8
    assert all(int(r["wall_ns"]) > 0 for r in observations)
    results = read(root / "paired.json")
    libraries = read(root / "paired-libraries.json")
    for case in cases:
        measured = {"search": [], "wall": [], "cycle": []}
        assert [r["round"] for r in libraries[case]] == [1, 2, 3]
        for i in range(1, 4):
            def row(mode, side):
                return by_key[case, i, mode, side]
            stock0, stock1 = row("stock", "P0"), row("stock", "P1")
            cold, hot = row("record-cold", "P1"), row("reuse", "P1")
            for stock in (stock0, stock1):
                assert int(stock["stock_observer_round"]) == i and int(stock["separate_stock_search_ns"]) > 0
            search_delta = int(cold["search_ns"]) - int(hot["search_ns"])
            wall_delta = int(stock1["wall_ns"]) - int(hot["wall_ns"])
            cycle_delta = wall_delta + int(stock0["wall_ns"]) - int(row("record", "P0")["wall_ns"])
            for label, value in zip(measured, (search_delta, wall_delta, cycle_delta)):
                measured[label].append(value / 1e9)
            for r in (hot, cold):
                assert int(r["inclusive_conflicts"]) == int(r["sat_conflicts"]) + int(r["root_conflicts"]) - int(r["root_conflicts_counter_delta"])
        for label, values in measured.items():
            report = results[case][label]
            assert all(isclose(a, b, abs_tol=1e-9) for a, b in zip(values, report["seconds"]))
            assert isclose(report["median_s"], median(values), abs_tol=1e-9)
            assert report["positive"] == sum(d > 0 for d in values)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raw", action="store_true")
    p.add_argument("--reports", type=Path, default=BASE / "reports")
    a = p.parse_args()
    root = a.reports / "evidence/d42"
    status = read(a.reports / "D4.2-status.json")
    assert status["implementation_sha"] and status["status"] in ("READY_FOR_REVIEW", "BLOCKED_CORRECTNESS")
    for name, sha in read(root / "checksums.json").items():
        assert digest(a.reports / name) == sha, name
    for table in root.glob("*.tsv"):
        with table.open(newline="") as f:
            rd = csv.reader(f, delimiter="\t")
            columns = next(rd)
            if table.name == "D4-fibonacci-121.tsv":
                batch = list(rd)
                assert columns[0] == "D4-selected-v1" and len(batch) == int(columns[2]) == 121
                assert all(len(r) == 3 + int(r[2]) for r in batch)
            else:
                assert all(len(r) == len(columns) for r in rd), table
    if status["status"] == "READY_FOR_REVIEW":
        audit = read(root / "audit.json")
        eq = read(root / "dependency-equivalence.json")
        assert status["acceptance"] == audit["outcomes"] and audit["outcomes"]["L1"] == "PASS"
        assert audit["gate"]["normal_clause_reproof_calls"] == 0 and len(eq) == 4
        assert sum(r["births"] for r in eq.values()) == 152817
        assert sum(v["baseline"] for case, v in eq.items() if case != "fib-snapshot-11") == 328
        for mode in ("identity", "unsigned", "signed"):
            assert sum(v["A1_A2"]["light"][mode]["eligible"] for v in eq.values() if "A1_A2" in v) == 43295
        for case, r in eq.items():
            assert r["combined"] >= r["baseline"] and r["births"] == r["independent"]["births"]
            assert r["equivalence"]["boundary_mismatch"] == r["equivalence"]["boundary_missing"] == 0
        properties = read(root / "properties.json")
        assert len(properties["functional"]) == 48 and len(properties["paired"]) == 96
        assert len(read(root / "compact-corruptions.json")) == 4
        assert read(root / "fixed-d4.json")["eligible"] == 121
        paired(root, status["cases"])
    for name, expected in status["raw_indices"].items():
        archive = root / "raw" / name
        assert digest(archive / "files.json") == expected
        if a.raw:
            verify_archive(archive, "", None)
    print("D4.2", status["status"], status["implementation_sha"], "verified")


if __name__ == "__main__":
    main()
