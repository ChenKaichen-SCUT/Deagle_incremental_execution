"""Serial D1 observations using the unmodified D0 input staging and limits."""
import argparse
import json
from pathlib import Path

from run_stock import BASE, run, sha, save
from summarize_stock import interpret

CASES = ("fib_updates_8", "circular-buffer", "airline_reservations_6")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("new_directory", type=Path)
    parser.add_argument("--manifest", action="store_true")
    args = parser.parse_args()
    binary, root = args.binary.resolve(), args.new_directory.resolve()
    root.mkdir(parents=True, exist_ok=False)
    digest = sha(binary)
    lock = BASE / "bench/manifest.json"
    specs = json.loads(lock.read_text())
    save(root / "plan.json", dict(binary_sha256=digest, inputs_sha256=sha(lock), cases=CASES,
                                  sides=["P0", "P1"], manifest=args.manifest, repeats=1))
    for name in CASES:
        for side in ("P0", "P1"):
            directory = root / name / side
            spec = dict(specs[name])
            if args.manifest:
                spec["argv"] = ["--d1-manifest", str(directory / "native.tsv"), *spec["argv"]]
            run(binary, spec, name, side, directory, digest)
            meta = json.loads((directory / "run.json").read_text())
            metrics, counterexamples = interpret(meta, (directory / "stdout").read_text())
            save(directory / "result.json", [metrics, counterexamples])


if __name__ == "__main__":
    main()
