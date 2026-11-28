"""Run only the PI-0 stock controls. Usage: stock-check.py RESEARCH_REPO STOCK_TREE BUILD_LOG_DIR NEW_OUT."""
import gzip
import itertools
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from frozen import STOCK, blob, digest, require, save

CONTROLS = (("smoke/worker_violation", "smoke"), ("fib_updates_8", "P0"), ("fib_updates_8", "P1"))


def properties(rows):
    # Absolute invocation directory is separately preserved in both raw outputs.
    result = []
    for row in rows:
        location = dict(row["sourceLocation"])
        location.pop("workingDirectory", None)
        result.append(dict(row, sourceLocation=location))
    return result


def finite_fibonacci():
    maxima = [0, 0]
    count = 0
    for left_positions in itertools.combinations(range(16), 8):
        left_steps = set(left_positions)
        for i, bias in enumerate((1, 0)):
            left = right = 1
            for step in range(16):
                if step in left_steps:
                    left += right + bias
                else:
                    right += left
            maxima[i] = max(maxima[i], left, right)
        count += 1
    return dict(schedules=count, old_max_component=maxima[0], candidate_max_component=maxima[1])


def main(repo, tree, build, out):
    binary = tree / "src/cbmc/deagle_exe"
    require(digest(binary.read_bytes()) == STOCK, "stock ELF differs from D0")
    out.mkdir(parents=True, exist_ok=False)
    manifest = json.loads(blob(repo, "bench/manifest.json"))
    old = {(v["case"], v["side"]): v for v in
           json.loads(blob(repo, "reports/evidence/d0/stock/metrics.json"))}
    oracle = json.loads(blob(repo, "reports/evidence/d0/independent-checks.json"))["fib_updates_8"]
    comparisons = []
    with tempfile.TemporaryDirectory() as t:
        bench = Path(t) / "dependency-reuse/bench"
        scripts = bench.parent / "scripts"
        scripts.mkdir(parents=True)
        for name in ("run_stock", "lock_build", "summarize_stock", "check_witnesses", "freeze_inputs"):
            (scripts / (name + ".py")).write_bytes(blob(repo, "scripts/" + name + ".py"))
        sys.path.insert(0, str(scripts))
        from run_stock import run
        from summarize_stock import interpret
        from check_witnesses import fib_trace
        # Use the frozen D0 ELF/link verifier on this build's original transcripts.
        locks = Path(t) / "link"
        locks.mkdir()
        for src, dst in (("build.log", "build.log"), ("build-time.txt", "time.txt"),
                         ("start.utc", "start.utc"), ("end.utc", "end.utc")):
            (locks / dst).symlink_to(build / src)
        subprocess.run([sys.executable, str(scripts / "lock_build.py"), str(tree), str(locks)], check=True)
        shutil.copyfile(locks / "build.json", out / "build.json")
        (out / "build.log.gz").write_bytes(gzip.compress((build / "build.log").read_bytes(), mtime=0))
        for case, side in CONTROLS:
            spec = manifest[case]
            for src, checksum in spec["files_sha256"].items():
                staged = bench / case / src
                staged.parent.mkdir(parents=True, exist_ok=True)
                data = blob(repo, "bench/" + case + "/" + src)
                require(digest(data) == checksum, "different frozen input " + src)
                staged.write_bytes(data)
            with tempfile.TemporaryDirectory() as wd:
                raw = Path(wd) / case / side
                run(binary, spec, case, side, raw, STOCK)
                meta = json.loads((raw / "run.json").read_bytes())
                dest = out / case / side
                dest.mkdir(parents=True)
                shutil.copyfile(raw / "run.json", dest / "run.json")
                for name in ("stdout", "stderr"):
                    data = (raw / name).read_bytes()
                    require(digest(data) == meta[name + "_sha256"], name)
                    (dest / (name + ".gz")).write_bytes(gzip.compress(data, mtime=0))
                require(not meta["timed_out"], "stock timeout")
                row, failures = interpret(meta, (raw / "stdout").read_text())
                expected = old[case, side]
                require(properties(row["properties"]) == properties(expected["properties"]), "property drift")
                for k in ("target_status", "classification", "cProverStatus", "trace_step_counts",
                          "unwinding_iterations", "unwinding_property_ids", "unwinding_stop_or_warning",
                          "enabled_unwinding_assertions", "adapter_query_count", "closure_completion_count"):
                    require(row[k] == expected[k], f"{case}/{side}: {k}")
                require(len(row["queries"]) == len(expected["queries"]) == 1, "unexpected query count")
                for k in ("reported_variables", "live_clauses", "native_cumulative", "adapter_message"):
                    require(row["queries"][0][k] == expected["queries"][0][k], "stock query drift: " + k)
                visible = None
                if case == "fib_updates_8" and side == "P0":
                    visible = fib_trace(failures[spec["target"]]["trace"])
                    require(visible == oracle["observed_P0"], "independent witness differs")
                elif case.startswith("smoke/"):
                    trace = failures[spec["target"]]["trace"]
                    require(any(s.get("stepType") == "assignment" and s.get("lhs") == "flag" and
                                s.get("value", {}).get("data") == "1" for s in trace), "missing flag=1")
                    visible = {"assignment": "flag=1", "failed_property": trace[-1]["property"]}
                save(dest / "result.json", row)
                comparisons.append(dict(case=case, side=side, result=row["classification"],
                                        native_query=row["queries"][0]["adapter_message"],
                                        properties=len(row["properties"]), target=spec["target"],
                                        steps=row["trace_step_counts"], visible=visible,
                                        wall_ns=meta["wall_ns"], peak_rss_kib=meta["peak_rss_kib"]))
    finite = finite_fibonacci()
    require(all(finite[k] == oracle[k] for k in finite), "independent finite schedule result")
    save(out / "checks.json", dict(matched_D0=True, finite_oracle=finite, controls=comparisons))


if __name__ == "__main__":
    main(*(Path(arg).resolve() for arg in sys.argv[1:]))
