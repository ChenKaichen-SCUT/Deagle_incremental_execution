"""Restore D0 from named Git objects. The experiment runner only reads the freeze."""
import argparse
import difflib
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HISTORY = "efaca29d9fa74777e5d1224efec3a95539030ff2"
DATASET = "06510d4999c4b1030945e83a50c9ef73e3db690b"
ADAPTATIONS = {"fib_updates_8": "fib_updates", "airline_reservations_6": "airline_reservations"}
CIRCULAR = "datasets/stage-12-hard-pairs/circular-buffer"
SMOKE = {"worker_violation": "worker.assertion.1", "join_pass": "main.assertion.1"}


def blob(repo, rev, name):
    return subprocess.check_output(["git", "-C", str(repo), "cat-file", "blob", f"{rev}:{name}"])


def sha(data):
    return hashlib.sha256(data).hexdigest()


def hashes(directory):
    return {p.relative_to(directory).as_posix(): sha(p.read_bytes())
            for p in sorted(directory.rglob("*")) if p.is_file()}


def unpack(repo, rev, src, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob(repo, rev, src))


def restore(repo, out):
    # Materialize only the modules/templates used by the published expanded_case and validate.
    modules = ["scripts/stage7/inputs.py", "incdeagle/model/identity.py", "incdeagle/repair.py",
               "incdeagle/counterexample.py", "incdeagle/adapters/deagle.py", "scripts/stage2/check_case.py",
               "scripts/stage1/run_evidence.py", "configs/project.yaml", "configs/toolchain.lock.json"]
    cases = {}
    matrix = json.loads(blob(repo, HISTORY, "reports/evidence/stage-07/matrix.json"))
    with tempfile.TemporaryDirectory() as temp:
        frozen = Path(temp)
        sources = modules + ["cases/batch_total/" + f for f in ("gamma.json", "phi.json", "task.yaml")]
        for name, template in ADAPTATIONS.items():
            sources.append(f"tests/stage7/{name}/spec.json")
            sources += [f"tests/stage7/{template}/{f}"
                        for f in ("harness.c", "old/program.c", "candidate/program.c")]
        for f in sources:
            unpack(repo, HISTORY, f, frozen / f)
        sys.path.insert(0, str(frozen))
        from scripts.stage7.inputs import expanded_case, validate

        for name in ADAPTATIONS:
            case = out / name
            expanded_case(case)  # checks each replacement count
            old = (case / "old/program.c").read_text().splitlines(True)
            new = (case / "candidate/program.c").read_text().splitlines(True)
            patch = "".join(difflib.unified_diff(old, new, fromfile="a/program.c", tofile="b/program.c"))
            (case / "patch.diff").write_bytes(patch.encode())
            expected = matrix[name]["files"]
            if hashes(case) != expected:
                raise ValueError(f"{name}: seven frozen file hashes do not match the published matrix")
            validate(out, dict(matrix[name], case_dir=name))  # also checks patch application in a temp dir
            spec = json.loads((frozen / f"tests/stage7/{name}/spec.json").read_bytes())
            gamma = json.loads((case / "gamma.json").read_bytes())
            cases[name] = dict(target=gamma["target_property"], origin=spec["origin"],
                               archive_commit=HISTORY, spec=f"tests/stage7/{name}/spec.json",
                               checked_replacements=spec["harness_replacements"], files_sha256=expected,
                               argv=gamma["source_argv"] + gamma["verification_output"] + [gamma["translation_unit"]],
                               limits=gamma["limits"], inputs={
                                   "P0": {"program.c": "old/program.c", "harness.c": "harness.c"},
                                   "P1": {"program.c": "candidate/program.c", "harness.c": "harness.c"}})

    case = out / "circular-buffer"
    for f in ("task.yaml", "patch.diff", "provenance.json", "unreach-call.prp",
              "old/upstream.yml", "new/upstream.yml", "old/program.i", "new/program.i"):
        unpack(repo, DATASET, f"{CIRCULAR}/{f}", case / f)
        if (case / f).read_bytes() != blob(repo, HISTORY, f"{CIRCULAR}/{f}"):
            raise ValueError(f"{f}: release and recovery commits differ")
    # The dataset's task.yaml is JSON-compatible YAML.
    task = json.loads((case / "task.yaml").read_bytes())
    provenance = json.loads((case / "provenance.json").read_bytes())
    files = hashes(case)
    expected = {s["file"]: s["sha256"] for s in task["sides"].values()}
    expected.update({task["property"]: task["property_sha256"], "patch.diff": provenance["patch_sha256"]})
    if any(files[k] != digest for k, digest in expected.items()):
        raise ValueError("circular-buffer: source/property/patch checksum mismatch")
    with tempfile.TemporaryDirectory() as temp:
        p = Path(temp) / "program.i"
        shutil.copyfile(case / "old/program.i", p)
        subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "-i", str(case / "patch.diff")],
                       cwd=temp, check=True, stdout=subprocess.PIPE)
        if p.read_bytes() != (case / "new/program.i").read_bytes():
            raise ValueError("circular-buffer patch does not reproduce P1")
    cases[case.name] = dict(target="reach_error.assertion.1", origin=task["binding"],
                            archive_commit=DATASET, files_sha256=files, argv=task["argv"],
                            limits={"timeout_seconds": task["limits"]["timeout_s"],
                                    "memory_bytes": task["limits"]["memory_gib"] * 2**30},
                            inputs={"P0": {"program.i": "old/program.i"}, "P1": {"program.i": "new/program.i"}})
    for name, target in SMOKE.items():
        f = name + ".c"
        case = out / "smoke" / name
        unpack(repo, HISTORY, f"tests/stage1/{f}", case / f)
        cases[f"smoke/{name}"] = dict(target=target, archive_commit=HISTORY, files_sha256=hashes(case),
                                      argv=["--function", "main", "--deagle-closure", "--mm", "sc", "--32",
                                            "--unwind", "3", "--unwinding-assertions", "--trace", "--json-ui", f],
                                      limits={"timeout_seconds": 60, "memory_bytes": 2**30},
                                      inputs={"smoke": {f: f}})
    (out / "manifest.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("historical_repo", type=Path)
    parser.add_argument("new_directory", type=Path)
    args = parser.parse_args()
    out = args.new_directory.resolve()
    if out.exists():
        parser.error("the freeze needs a new destination")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as temp:
        staging = Path(temp) / "bench"
        restore(args.historical_repo.resolve(), staging)
        staging.rename(out)


if __name__ == "__main__":
    main()
