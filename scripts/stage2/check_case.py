"""Check a stage-2 snapshot with the locked full baseline and save replayable evidence."""
import argparse
import gzip
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts/stage1"))
from incdeagle.adapters.deagle import classify
from incdeagle.counterexample import normalize
from run_evidence import capture, sha256, write_json

BINARY = ROOT / "third_party/deagle-baseline/src/cbmc/deagle_exe"


def load_case(case):
    task = yaml.safe_load((case / "task.yaml").read_bytes())
    gamma = json.loads((case / task["verification_config"]).read_bytes())
    phi = json.loads((case / task["property"]["file"]).read_bytes())
    lines = (case / "harness.c").read_text(encoding="utf-8").splitlines()
    statement = lines[phi["source"]["line"] - 1].strip()
    fingerprint = hashlib.sha256(statement.encode()).hexdigest()
    limits = yaml.safe_load((ROOT / "configs/project.yaml").read_bytes())["resources"]["verification"]
    checks = [
        task["case_id"] == case.name, task["repair"]["allowed_files"] == ["program.c"],
        task["entry"] == gamma["entry"] == phi["source"]["function"], phi["id"] == gamma["target_property"] == task["property"]["id"],
        phi["assertion"] == statement, fingerprint == phi["assertion_sha256"] == task["property"]["original_assertion_fingerprint"],
        sha256(case / "harness.c") == gamma["harness_sha256"], task["semantics"] == gamma["semantics"],
        gamma["limits"] == task["limits"] == {k: limits[k] for k in ("timeout_seconds", "memory_bytes")},
        gamma["included_source"] == "program.c", gamma["translation_unit"] == phi["source"]["file"] == "harness.c",
        gamma["binary_sha256"] == json.loads((ROOT / "configs/toolchain.lock.json").read_bytes())["repositories"]["deagle"]["binary_sha256"]["third_party/deagle-baseline/src/cbmc/deagle_exe"],
    ]
    sem = gamma["semantics"]
    expected = ["--function", gamma["entry"], "--" + sem["backend"], "--mm", sem["memory_model"],
                "--" + str(sem["target_bits"]), "--unwind", str(sem["unwind"])]
    if sem["check_unwinding"]:
        expected.append("--unwinding-assertions")
    if not all(checks) or gamma["source_argv"] != expected + sem["compiler_flags"]:
        raise ValueError("Protected case inputs disagree with their manifest")
    return task, gamma, phi


def compress(path):
    dst = path.with_name(path.name + ".gz")
    dst.write_bytes(gzip.compress(path.read_bytes(), mtime=0))
    path.unlink()
    return dst.name


def check(case, version, output):
    task, gamma, phi = load_case(case)
    if sha256(BINARY) != gamma["binary_sha256"]:
        raise ValueError("Unexpected baseline binary")
    output.mkdir(parents=True, exist_ok=False)
    root_runs = ROOT / "runs/stage-02"
    root_runs.mkdir(parents=True, exist_ok=True)
    snapshot = case / (task["old_source"] if version == "old" else task["candidate_source"])
    if snapshot.is_symlink() or not snapshot.is_file():
        raise ValueError("Expected a regular source snapshot")
    semantic_inputs = {label: sha256(case / label) for label in ("harness.c", "phi.json", "gamma.json", "task.yaml")}
    inputs = {"program.c": sha256(snapshot), **semantic_inputs}
    report = {"case": case.name, "version": version, "input_sha256": inputs, "deagle_sha256": sha256(BINARY),
              "runs": {}, "resource_limits": gamma["limits"]}
    with tempfile.TemporaryDirectory(prefix=case.name + "-", dir=root_runs) as tmp:
        cwd = Path(tmp)
        shutil.copyfile(snapshot, cwd / "program.c")
        shutil.copyfile(case / "harness.c", cwd / "harness.c")
        if sha256(cwd / "program.c") != inputs["program.c"] or sha256(cwd / "harness.c") != inputs["harness.c"]:
            raise ValueError("Staged translation unit differs")
        base = [BINARY, *gamma["source_argv"]]
        commands = [
            ("syntax", ["gcc", "-std=gnu11", "-pthread", "-fsyntax-only", "harness.c"], {}),
            ("frontend", [*base, *gamma["frontend_mode"], "harness.c"], {}),
            ("verify", [*base, *gamma["verification_output"], "harness.c"],
             {"INCDEAGLE_JSON_OUTPUT": str(cwd / "result.json")}),
        ]
        for name, cmd, env in commands:
            r = capture(output, name, cmd, cwd=cwd, environment=env)
            report["runs"][name] = r
            out = output / r["stdout"]
            text = out.read_text(encoding="utf-8", errors="replace")
            r["stdout"] = compress(out)
            r["stderr"] = compress(output / r["stderr"])
            write_json(output / "run.json", report)
            if name == "frontend":
                expected = "// assertion " + phi["assertion"][len("assert("):-2]
                if r["exit_code"] or "main /* main */" not in text or expected not in text or "Use Deagle's closure solver" in text:
                    raise ValueError("GOTO front end did not emit the original main and assertion before solver selection")
                r["checked_assertion_comment"] = expected
            elif name == "verify":
                raw = cwd / "result.json"
                if raw.exists():
                    dest = output / "result.json"
                    shutil.copyfile(raw, dest)
                    r["document_sha256"] = sha256(dest)
                    r["document"] = compress(dest)
                if r["exit_code"] not in (0, 5, 10):
                    report["classification"] = "TIMEOUT" if r["exit_code"] == 124 else "ERROR"
                    write_json(output / "run.json", report)
                    raise RuntimeError(f"Verifier returned {r['exit_code']}")
                if r["exit_code"] == 5:
                    report["classification"] = "UNKNOWN"
                    write_json(output / "run.json", report)
                if not raw.is_file() or (r["exit_code"] in (0, 10) and (
                        "Use Deagle's closure solver" not in text or "Set Deagle closure solver's graph" not in text)):
                    raise ValueError("Missing result or Closure backend evidence")
                verdict, row = classify(raw.read_bytes(), r["exit_code"], phi)
                report.update(verdict)
                if version == "old" and verdict["classification"] != "VIOLATION":
                    raise ValueError("Old case requires a confirmed target violation")
                if verdict["classification"] == "VIOLATION":
                    cex = normalize(row, phi, gamma, inputs, r["document"], version=version)
                    write_json(output / ("cex0.json" if version == "old" else "cex1.json"), cex)
        if any(sha256(case / k) != v for k, v in semantic_inputs.items()) or sha256(snapshot) != inputs["program.c"]:
            raise ValueError("Input changed during verification")
    write_json(output / "run.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=sorted(p.parent.name for p in (ROOT / "cases").glob("*/task.yaml")))
    parser.add_argument("version", choices=("old", "candidate"))
    parser.add_argument("--out", type=Path, required=True, help="new directory for this run")
    args = parser.parse_args()
    result = check(ROOT / "cases" / args.case, args.version, args.out.resolve())
    print(args.case, args.version, result["classification"])


if __name__ == "__main__":
    main()
