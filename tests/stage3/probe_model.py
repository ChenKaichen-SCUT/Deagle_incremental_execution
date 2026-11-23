#!/usr/bin/env python3
"""Native interface regressions on temporary copies of the batch harness."""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.stage3.session import BINARY, memory_max
from scripts.stage2.check_case import load_case
from incdeagle.adapters.deagle import classify
from incdeagle.model.identity import file_sha, read, save
from incdeagle.model.observe import build_model
from incdeagle.model.compare import compare_mapping


def run(root):
    case = ROOT / "cases/batch_total"
    task, gamma, phi = load_case(case)
    if int(memory_max()) != gamma["limits"]["memory_bytes"] or file_sha(BINARY) != read(ROOT / "configs/stage03.lock.json")["development_sha256"]:
        raise RuntimeError("Probe environment differs from the verification lock")
    root.mkdir(parents=True, exist_ok=False)
    original = (case / task["old_source"]).read_text()
    statement = "    shipped_units += boxes * 2;"
    variants = {"original": original, "shifted": original.replace(statement, "\n" + statement),
                "duplicate": original.replace(statement, statement + "\n" + statement),
                "loop": original.replace(statement, "    unsigned i = 0;\n    while (i < 6) {\n"
                                          "        shipped_units += boxes;\n        ++i;\n    }")}
    models, results = {}, {}
    for name, src in variants.items():
        d = root / name
        d.mkdir()
        (d / "program.c").write_text(src)
        shutil.copyfile(case / "harness.c", d / "harness.c")
        cmd = [str(BINARY), *gamma["source_argv"], *gamma["verification_output"], "harness.c"]
        env = dict(os.environ, LC_ALL="C", INCDEAGLE_OBSERVE_DIR=str(d), INCDEAGLE_JSON_OUTPUT=str(d / "result.json"))
        with (d / "diagnostic.stdout").open("wb") as stdout, (d / "diagnostic.stderr").open("wb") as stderr:
            rc = subprocess.run(cmd, cwd=d, env=env, stdout=stdout, stderr=stderr, timeout=gamma["limits"]["timeout_seconds"]).returncode
        result, _ = classify((d / "result.json").read_bytes(), rc, phi)
        models[name] = build_model(d, phi["id"])
        results[name] = {"document_sha256": file_sha(d / "result.json"), "process_exit": rc, **result}
    def writes(name):
        m = models[name]
        return [e for e in m["events"] if e["key"]["role"] == "write" and e["bucket"] == "shipped_units"
                and m["mappings"]["sources"][e["key"]["source"]]["locations"][0]["function"] == "record_batch"]
    original_write, = writes("original")
    shifted_write, = writes("shifted")
    assert original_write["identity_unique"] and shifted_write["identity_unique"]
    assert original_write["id"] == shifted_write["id"]
    assert shifted_write["semantic"]["solver_line"] == original_write["semantic"]["solver_line"] + 1
    assert shifted_write["fingerprint"] != original_write["fingerprint"]
    duplicates = writes("duplicate")
    assert len(duplicates) == 2 and all(not e["identity_unique"] for e in duplicates)
    rejected = compare_mapping(models["original"]["mappings"]["sources"], models["duplicate"]["mappings"]["sources"])["rejected"]
    assert original_write["key"]["source"] in rejected
    loop = models["loop"]
    loop_contexts = [loops for event in writes("loop") for _, _, loops in event["key"]["calls"] if loops]
    unwind_ids = loop["unwinding_properties"]
    assert loop_contexts and all(anchor != "unknown-loop" for ctx in loop_contexts for anchor, _ in ctx)
    assert unwind_ids and any(results["loop"]["unwinding_properties"].get(i) == "FAILURE" for i in unwind_ids)
    summary = {"results": results, "line_shift": {"event": original_write["id"],
               "solver_lines": [x["semantic"]["solver_line"] for x in (original_write, shifted_write)],
               "value_unchanged": original_write["semantic"]["value"] == shifted_write["semantic"]["value"],
               "fingerprints": [original_write["fingerprint"], shifted_write["fingerprint"]]},
               "duplicates": {"occurrences": len(duplicates), "eligible": sum(e["identity_unique"] for e in duplicates),
                              "rejected_source": original_write["key"]["source"]},
               "loop": {"unwinding_properties": unwind_ids, "anchored_iterations": loop_contexts},
               "baseline_cases_written": False}
    save(root / "probes.json", summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--contained", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.contained:
        run(args.out.resolve())
    else:
        subprocess.run(["systemd-run", "--quiet", "--pipe", "--wait", "--collect", "-p", "WorkingDirectory=" + str(ROOT),
                        "-p", "MemoryMax=21474836480", "--", sys.executable, "-B", str(Path(__file__).resolve()),
                        "--out", str(args.out.resolve()), "--contained"], check=True)
