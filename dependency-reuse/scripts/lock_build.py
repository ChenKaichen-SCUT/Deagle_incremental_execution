"""Bind the stock executable, linked Closure members and build transcript to the fixed tree."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

UPSTREAM = "d8c79eaba5df03b1a013dc6ffbb3a1e249485c1e"
TREE = "ee983048136026478a6af5774ab20077b273db2f"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock", type=Path)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    root, evidence = args.stock.resolve(), args.evidence.resolve()

    def output(*argv):
        return subprocess.check_output(argv, cwd=root, text=True).strip()

    if (output("git", "rev-parse", "HEAD"), output("git", "rev-parse", "HEAD^{tree}")) != (UPSTREAM, TREE):
        raise ValueError("unexpected source revision")
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--"], cwd=root, check=True)
    binary = root / "src/cbmc/deagle_exe"
    archive = "src/solvers/solvers.a"
    components = ("ClosureSolver", "Closure", "ClosureTypes", "Solver", "satcheck_minisat2")
    members = {}
    for filename in output("ar", "t", archive).splitlines():
        member = (root / filename).resolve()
        if member.stem in components:
            source = member.with_suffix(".cpp" if member.stem == "satcheck_minisat2" else ".cc")
            members[member.stem] = {"object": str(member.relative_to(root)), "sha256": sha(member),
                                    "source": str(source.relative_to(root)), "source_sha256": sha(source)}
    symbols = [s for s in output("nm", "-C", "--defined-only", str(binary)).splitlines()
               if re.search(r" T Minisat::ClosureSolver::(solve_|search|analyze|propagate)\(", s)]
    if set(members) != set(components) or len(symbols) != 4:
        raise ValueError("missing native object or linked implementation")
    log = (evidence / "build.log").read_text()
    link = next(s for s in log.splitlines() if " -o deagle_exe " in s and "../solvers/solvers.a" in s)
    compiled = [s for s in log.splitlines() if " -c " in s and s.endswith("/ClosureSolver.cc")]
    if len(compiled) != 1:
        raise ValueError("missing fresh ClosureSolver compilation")
    receipt = dict(source_commit=UPSTREAM, source_tree=TREE, tracked_source_diff=False,
                   binary_path=str(binary), binary_sha256=sha(binary), binary_bytes=binary.stat().st_size,
                   binary_version=output(str(binary), "--version"),
                   build_command=["make", "-C", "src", "-j12", "cbmc.dir"], patches=[],
                   compiler=output("g++", "--version").splitlines()[0],
                   bison=output("bison", "--version").splitlines()[0], flex=output("flex", "--version"),
                   make=output("make", "--version").splitlines()[0], linker=output("ld", "--version").splitlines()[0],
                   libraries=output("ldd", str(binary)).splitlines(), closure_compile=compiled[0],
                   final_link=link, thin_archive=archive, archive_member_count=len(output("ar", "t", archive).splitlines()),
                   members=members, defined_symbols=symbols, start_utc=(evidence / "start.utc").read_text().strip(),
                   end_utc=(evidence / "end.utc").read_text().strip(), build_log_sha256=sha(evidence / "build.log"),
                   gnu_time=(evidence / "time.txt").read_text().splitlines())
    (evidence / "build.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(binary, receipt["binary_sha256"])


if __name__ == "__main__":
    main()
