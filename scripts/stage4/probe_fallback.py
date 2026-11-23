#!/usr/bin/env python3
"""Exercise budget, frontend provenance and native GOTO rejection with real solvers."""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from incdeagle.model.identity import save
from scripts.stage2.check_case import check
from scripts.stage4.session import CASES, run_pair


def probe(out):
    out.mkdir(parents=True, exist_ok=False)
    result = {}
    refusals = {
        "capacity": "checkpoint_budget_or_multithreaded_host",
        "header": "config_headers_or_layout_changed",
        "rhs_shape": "non_scalar_or_address_sensitive_assignment",
    }
    source = CASES["batch_total"]
    for name, expected in refusals.items():
        run = out / name
        case = run / "inputs/batch_total"
        case.mkdir(parents=True)
        for version in ("old", "candidate"):
            (case / version).mkdir()
            shutil.copyfile(source / version / "program.c", case / version / "program.c")
        for filename in ("task.yaml", "harness.c", "phi.json", "gamma.json"):
            shutil.copyfile(source / filename, case / filename)
        program = case / "candidate/program.c"
        if name == "header":
            program.write_bytes(b"#include <limits.h>\n" + program.read_bytes())
        if name == "rhs_shape":
            code = program.read_bytes()
            if code.count(b"boxes * 3") != 1:
                raise ValueError("Unexpected batch_total fixture")
            program.write_bytes(code.replace(b"boxes * 3", b"boxes + 4"))

        session = run_pair(case, run / "pair", checkpoint_bytes=1 if name == "capacity" else None)
        oracle = check(case, "candidate", run / "independent")
        native = session["native"]
        if session["path"] != "full_fallback" or session["fallback_reason"] != expected:
            raise ValueError(f"{name} expected {expected} but got {session['fallback_reason']}")
        if native["reused_prefix_symex_steps"] or native["executed_symex_steps"] <= 0:
            raise ValueError(f"{name} did not perform a full candidate build")
        if any(oracle[key] != value for key, value in session["candidate"].items()):
            raise ValueError(f"{name} differs from the independent full baseline")
        result[name] = {
            "status": session["candidate"]["classification"],
            "reason": session["fallback_reason"],
            "native_dispatches": native["executed_symex_steps"],
            "reused_prefix": native["reused_prefix_symex_steps"],
            "baseline_exit": oracle["runs"]["verify"]["exit_code"],
            "inputs": session["inputs_sha256"],
        }
        print(name, expected, native["executed_symex_steps"], result[name]["status"])
    save(out / "probes.json", result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--contained", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.contained:
        probe(args.out.resolve())
    else:
        subprocess.run([
            "systemd-run", "--quiet", "--pipe", "--wait", "--collect",
            "-p", "WorkingDirectory=" + str(ROOT), "-p", "MemoryMax=21474836480", "--",
            sys.executable, "-B", str(Path(__file__).resolve()), "--out", str(args.out.resolve()), "--contained",
        ], check=True)
