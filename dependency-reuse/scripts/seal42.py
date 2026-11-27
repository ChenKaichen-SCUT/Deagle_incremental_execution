"""Bind the D4.2 review to the measured binaries, verified raw indices and readable tables."""
import argparse
from pathlib import Path

from d42_prepare import read, save
from diff_d1 import digest
from run_stock import BASE


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("reports", type=Path)
    p.add_argument("implementation")
    a = p.parse_args()
    if len(a.implementation) != 40 or any(c not in "0123456789abcdef" for c in a.implementation):
        p.error("provide a full Git commit ID")
    reports = a.reports.resolve()
    evidence = reports / "evidence/d42"
    gate = read(evidence / "audit.json")
    plan = read(BASE / "configs/d42-plan.json")
    indices = {}
    volumes = {}
    for index in sorted((evidence / "raw").glob("*/files.json")):
        name = index.parent.name
        entries = read(index)["files"]
        blobs = list((index.parent / "objects").glob("*.gz"))
        assert entries and blobs
        indices[name] = digest(index)
        volumes[name] = dict(files=len(entries), original_bytes=sum(f["bytes"] for f in entries.values()),
                             objects=len(blobs), gzip_bytes=sum(f.stat().st_size for f in blobs))
    assert "release" in indices
    result = dict(stage="D4.2", status="READY_FOR_REVIEW", implementation_sha=a.implementation,
                  baseline_review=plan["baseline"], baseline_implementation=plan["baseline_implementation"],
                  official_upstream=plan["upstream"], historical_source=plan["old_project"],
                  stock_sha256=read(BASE / "configs/build.json")["binary_sha256"],
                  native_sha256=gate["gate"]["binary"], production_tools=gate["gate"]["tools"],
                  cases=plan["cases"], rounds=plan["repetitions"], preregistration_sha256=digest(BASE/"configs/d42-plan.json"),
                  acceptance=gate["outcomes"], raw_indices=indices, lossless_archives=volumes)
    save(reports / "D4.2-status.json", result)
    readable = sorted(reports.glob("D4.2*.md")) + [reports / "D4.2-status.json"]
    readable += sorted(p for p in evidence.iterdir() if p.is_file() and p.name != "checksums.json")
    save(evidence / "checksums.json", {p.relative_to(reports).as_posix(): digest(p) for p in readable})
    print(result["status"], result["native_sha256"], result["acceptance"])


if __name__ == "__main__":
    main()
