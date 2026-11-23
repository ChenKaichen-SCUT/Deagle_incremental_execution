"""Validate the fixed versions, diagnostic records and single-file patch without any API call."""
import argparse
import difflib
import gzip
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from check_case import ROOT, classify, load_case, normalize, sha256


def checked_read(path, expected, compressed=False):
    data = path.read_bytes()
    if compressed:
        data = gzip.decompress(data)
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"Hash mismatch in {path}")
    return data


def check_command(mode, command, gamma):
    if f"MemoryMax={gamma['limits']['memory_bytes']}" not in command:
        raise ValueError("Unexpected cgroup memory limit in recorded command")
    tail = command[command.index("--") + 1:]
    if tail[:3] != ["/usr/bin/timeout", "--kill-after=5", str(gamma["limits"]["timeout_seconds"])]:
        raise ValueError("Unexpected command timeout")
    if mode == "syntax":
        if tail[3:] != ["gcc", "-std=gnu11", "-pthread", "-fsyntax-only", "harness.c"]:
            raise ValueError("Unexpected auxiliary syntax command")
        return
    expected_mode = gamma["frontend_mode"] if mode == "frontend" else gamma["verification_output"]
    if PurePosixPath(tail[3]).parts[-5:] != ("third_party", "deagle-baseline", "src", "cbmc", "deagle_exe"):
        raise ValueError("Unexpected verifier path")
    if tail[4:] != [*gamma["source_argv"], *expected_mode, gamma["translation_unit"]]:
        raise ValueError("Recorded verifier arguments differ from the frozen configuration")


def validate(case):
    task, gamma, phi = load_case(case)
    old, new = (case / task[x] for x in ("old_source", "candidate_source"))
    for src in (old, new):
        if src.is_symlink() or sorted(p.name for p in src.parent.iterdir()) != ["program.c"] or not src.is_file():
            raise ValueError("File allowlist violation")
    patch = "".join(difflib.unified_diff(old.read_text(encoding="utf-8").splitlines(keepends=True), new.read_text(encoding="utf-8").splitlines(keepends=True),
                                         fromfile="a/program.c", tofile="b/program.c")).encode()
    if not patch:
        raise ValueError("Unchanged candidate")
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "program.c").write_bytes(old.read_bytes())
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        for flags in (["--check"], []):
            subprocess.run(["git", "-C", str(repo), "-c", "core.autocrlf=false", "apply", *flags, "-"], input=patch, check=True)
        if (repo / "program.c").read_bytes() != new.read_bytes():
            raise ValueError("Applied diff differs from candidate")

    review = json.loads((ROOT / "reports/evidence/stage-02/repair-review.json").read_bytes())[case.name]
    if review["candidate_sha256"] != sha256(new) or review["decision"] != "accepted_for_bounded_verification" or review["method"] != task["repair"]["method"]:
        raise ValueError("Candidate has no matching source review")
    summary = {"schema_version":1, "case":case.name, "property":phi["id"], "assertion_sha256":phi["assertion_sha256"],
               "method":task["repair"]["method"], "change_type":task["repair"]["change_type"],
               "only_changed_file":"program.c", "patch_replays_byte_for_byte":True, "source_review":review, "results":{}}
    files = [old, new, *(case / p for p in ("task.yaml", "harness.c", "phi.json", "gamma.json"))]
    for version, src in (("old", old), ("candidate", new)):
        directory = case / "evidence" / version
        run = json.loads((directory / "run.json").read_bytes())
        expected = {p:sha256(case / p) for p in ("task.yaml", "harness.c", "phi.json", "gamma.json")}
        expected["program.c"] = sha256(src)
        if run["version"] != version or run["case"] != case.name or run["input_sha256"] != expected or run["deagle_sha256"] != gamma["binary_sha256"]:
            raise ValueError(f"Snapshot mismatch in {directory}")
        files.append(directory / "run.json")
        if set(run["runs"]) != {"syntax", "frontend", "verify"} or run["resource_limits"] != gamma["limits"]:
            raise ValueError("Incomplete run or wrong resource settings")
        for mode, details in run["runs"].items():
            check_command(mode, details["command"], gamma)
            for stream in ("stdout","stderr"):
                path = directory / details[stream]
                content = checked_read(path,details[stream + "_sha256"],compressed=True)
                files.append(path)
                if mode == "frontend" and stream == "stdout" and details["checked_assertion_comment"].encode() not in content:
                    raise ValueError("Front-end property missing from IR")
        if run["runs"]["frontend"]["exit_code"] != 0:
            raise ValueError("Fixed front end rejected the candidate")
        details = run["runs"]["verify"]
        path = directory / details["document"]
        document = checked_read(path,details["document_sha256"],compressed=True)
        files.append(path)
        verdict, target = classify(document, details["exit_code"], phi)
        if any(run[k] != value for k, value in verdict.items()):
            raise ValueError("Result disagrees with native evidence")
        summary["results"][version] = verdict["classification"]
        if verdict["classification"] == "VIOLATION":
            cexfile = directory / ("cex0.json" if version == "old" else "cex1.json")
            if json.loads(cexfile.read_bytes()) != normalize(target, phi, gamma, expected, details["document"]):
                raise ValueError("Counterexample differs from original trace")
            files.append(cexfile)
        elif version == "old":
            raise ValueError("P0 lacks its required counterexample")
    if task["repair"]["method"] == "mini_deepseek":
        record = json.loads((ROOT / review["model_record"]).read_bytes())
        if record["exit_status"] != "Submitted" or record["candidate_sha256"] != sha256(new) or not record["protected_inputs_unchanged"]:
            raise ValueError("Candidate differs from the agent's submission")
        expected_agent_inputs = {"harness.c":case/"harness.c", "phi.json":case/"phi.json", "gamma.json":case/"gamma.json",
                                 "task.yaml":case/"task.yaml", "old/program.c":old, "cex0.json":case/"evidence/old/cex0.json"}
        if any(record["input_sha256"][k] != sha256(p) for k,p in expected_agent_inputs.items()):
            raise ValueError("Agent saw different inputs")
        old_run = json.loads((case / "evidence/old/run.json").read_bytes())
        if record["input_sha256"]["raw.json"] != old_run["runs"]["verify"]["document_sha256"]:
            raise ValueError("Agent did not receive the original trace")
        summary["model_record_sha256"] = sha256(ROOT / review["model_record"])
    summary["files_sha256"] = {p.relative_to(case).as_posix():sha256(p) for p in sorted(files)}
    summary["files_sha256"]["patch.diff"] = hashlib.sha256(patch).hexdigest()
    return patch, (json.dumps(summary,ensure_ascii=False,indent=2)+"\n").encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", nargs="*", help="defaults to all manifests")
    parser.add_argument("--write", action="store_true", help="create missing freeze files; refuse to replace divergent files")
    args = parser.parse_args()
    cases = sorted(p.parent for p in (ROOT / "cases").glob("*/task.yaml"))
    if args.case:
        by_name = {c.name:c for c in cases}
        cases = [by_name[name] for name in args.case]
    if not cases:
        raise ValueError("No case manifests")
    for case in cases:
        patch, manifest = validate(case)
        for path, expected in ((case/"patch.diff",patch),(case/"freeze.json",manifest)):
            if args.write and not path.exists():
                with path.open("xb") as out:
                    out.write(expected)
            if path.read_bytes() != expected:
                raise ValueError(f"Divergent frozen file: {path}")
        print(f"{case.name}: verified patch, source, property, configuration, counterexample and raw streams")


if __name__ == "__main__":
    main()
