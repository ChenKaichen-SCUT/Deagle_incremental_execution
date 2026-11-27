"""Check the frozen finite oracles, actual P0 trace projections and historical counter boundaries."""
import argparse
import gzip
import json
import math
import runpy
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

from freeze_inputs import DATASET, HISTORY, CIRCULAR, blob, hashes, sha, unpack
from run_stock import BASE, save


def require(check, message):
    if not check:
        raise ValueError(message)


def numeric(step):
    return int(step["value"]["data"].removesuffix("u"))


def fib_trace(trace):
    left = right = 1
    actions = []
    for s in trace:
        fn = s.get("sourceLocation", {}).get("function")
        if s["stepType"] != "assignment":
            continue
        if (fn, s.get("lhs")) == ("update_left", "left"):
            left += right + 1
            require(numeric(s) == left, "old Fibonacci left update disagrees with trace")
            actions.append(["L", left])
        if (fn, s.get("lhs")) == ("right_worker", "right"):
            right += left
            require(numeric(s) == right, "old Fibonacci right update disagrees with trace")
            actions.append(["R", right])
    require(Counter(k for k, _ in actions) == {"L": 8, "R": 8} and max(left, right) > 2584,
            "trace does not falsify the protected Fibonacci bound")
    return dict(actions=actions, final_left=left, final_right=right)


def sale_trace(trace, program):
    lines = [l.strip() for l in program.read_text().splitlines()]
    read, write = str(1 + lines.index("observed = sold;")), str(1 + lines.index("sold = observed + 1u;"))
    sold, actions, saved, writes = 0, [], {}, set()
    for s in trace:
        loc = s.get("sourceLocation", {})
        if s["stepType"] != "assignment" or (loc.get("file"), loc.get("function")) != ("program.c", "reserve_seat"):
            continue
        thread = s["thread"]
        if (s.get("lhs"), loc.get("line")) == ("observed", read):
            require(thread not in saved and numeric(s) == sold, "old booking read disagrees with trace")
            saved[thread] = sold
            actions.append([thread, "read", sold])
        if (s.get("lhs"), loc.get("line")) == ("sold", write):
            require(thread not in writes and thread in saved and saved[thread] < 5, "unexpected booking write")
            sold = saved[thread] + 1
            require(numeric(s) == sold, "stale booking update disagrees with trace")
            writes.add(thread)
            actions.append([thread, "write", sold])
    require(len(saved) == 6 and writes == {t for t, v in saved.items() if v < 5} and sold != 5,
            "trace does not falsify protected capacity")
    return dict(actions=actions, final_sold=sold)


def buffer_trace(trace):
    fields = {("t1", "i"), ("t2", "i"), ("t2", "return_value_removeLogElement"),
              ("insertLogElement", "next"), ("removeLogElement", "first")}
    rows = []
    for s in trace:
        fn = s.get("sourceLocation", {}).get("function")
        if (fn, s.get("lhs")) in fields or s["stepType"] == "failure":
            rows.append([s.get("thread"), fn, s.get("lhs"), s.get("value", {}).get("data"), s["stepType"]])
    return rows


def historical_counters(repo, metrics):
    # Disambiguate the stage-12 query deltas using its original start/end rows.
    prefix = "reports/evidence/stage-12/raw/"
    index = json.loads(blob(repo, DATASET, prefix + "files.json"))
    baseline = json.loads(blob(repo, DATASET, CIRCULAR + "/baseline.json"))["results"]
    names = [("P0", "old", "buffer-b8"), ("P1", "new", "buffer-fix-b8")]
    keys = {side: index[f"server/formal/{job}/native-state.tsv"] for side, _, job in names}
    cache = repo / "runs/hard-pairs-admin/release-objects.zip"
    if cache.is_file():
        with zipfile.ZipFile(cache) as archive:
            records = {side: archive.read(key) for side, key in keys.items()}
    else:
        with tempfile.TemporaryFile() as tmp:
            parts = json.loads(blob(repo, DATASET, prefix + "parts.json"))["parts"]
            for part in parts:
                data = blob(repo, DATASET, prefix + part["file"])
                require(sha(data) == part["sha256"], "bad historical archive part")
                tmp.write(data)
            tmp.seek(0)
            with zipfile.ZipFile(tmp) as archive:
                records = {side: archive.read(key) for side, key in keys.items()}
    result = {}
    cols = ("sat_conflicts", "sat_propagations", "theory_propagations", "theory_cycle_conflicts")
    for side, hist, _ in names:
        data = records[side]
        require(sha(data) == keys[side] == baseline[hist]["raw_sha256"]["native-state.tsv"],
                "stage-12 state hash mismatch")
        start, end = [list(map(int, l.split()))[12:16] for l in data.splitlines()]
        delta = [b - a for a, b in zip(start, end)]
        official = baseline[hist]["counters"]
        require(delta == [official[k] for k in ("conflicts", "propagations", "theory_propagations", "theory_conflicts")],
                "published stage-12 delta does not match snapshots")
        observed = metrics["circular-buffer", side]["queries"][0]["native_cumulative"]
        result[side] = dict(old_native_state_sha256=keys[side], historical_query_start=dict(zip(cols, start)),
                            historical_query_end=dict(zip(cols, end)), historical_query_delta=dict(zip(cols, delta)),
                            stock_end_agrees=all(observed[k] == v for k, v in zip(cols, end)))
    return result


def audit(repo, evidence):
    metrics = {(r["case"], r["side"]): r for r in json.loads((evidence / "metrics.json").read_bytes())}
    traces = json.loads(gzip.decompress((evidence / "counterexamples.json.gz").read_bytes()))
    bench = BASE / "bench"
    locked = json.loads((bench / "manifest.json").read_bytes())
    matrix = json.loads(blob(repo, HISTORY, "reports/evidence/stage-07/matrix.json"))
    fib, airline, buffer = "fib_updates_8", "airline_reservations_6", "circular-buffer"
    for name in (fib, airline, buffer):
        files = hashes(bench / name)
        require(files == locked[name]["files_sha256"], "bench differs from manifest")
        if name in (fib, airline):
            require(files == matrix[name]["files"], "bounded adaptation differs from stage 7")
        else:
            require(all(value == sha(blob(repo, DATASET, f"{CIRCULAR}/{k}")) for k, value in files.items()),
                    "buffer differs from the frozen dataset")
        require(metrics[name, "P0"]["classification"] == "VIOLATION" and
                metrics[name, "P1"]["classification"] == "BOUNDED_PASS", f"{name}: native / oracle disagreement")

    stage7 = json.loads(blob(repo, HISTORY, "reports/evidence/stage-07/schedule-oracles.json"))
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        script = folder / "oracles.py"
        unpack(repo, HISTORY, "scripts/stage7/oracles.py", script)
        funcs = runpy.run_path(str(script))
        f = dict(schedules=math.comb(16, 8), bound=2584, old_max_component=funcs["fibonacci"](8, 1),
                 candidate_max_component=funcs["fibonacci"](8, 0))
        a = dict(capacity=5, old_reachable_final_sold=funcs["sales"](6, 5, False),
                 candidate_reachable_final_sold=funcs["sales"](6, 5, True))
        require((f, a) == (stage7[fib], stage7[airline]), "stage-7 finite oracles disagree")
        d = folder / "scripts/hard_pairs"
        for n in ("prepare.py", "followup.py"):
            unpack(repo, DATASET, "scripts/hard_pairs/" + n, d / n)
        sys.path.insert(0, str(d))
        import followup
        followup.E = folder  # redirect only the oracle's output file
        followup.buffer_model()
        b = json.loads((folder / "buffer-functional.json").read_bytes())
        require(b == json.loads(blob(repo, DATASET, "reports/evidence/stage-12/buffer-functional.json")),
                "stage-12 finite buffer oracle disagrees")
    f["observed_P0"] = fib_trace(traces[fib + "/P0"][locked[fib]["target"]]["trace"])
    a["observed_P0"] = sale_trace(traces[airline + "/P0"][locked[airline]["target"]]["trace"],
                                  bench / airline / "old/program.c")
    projection = buffer_trace(traces[buffer + "/P0"][locked[buffer]["target"]]["trace"])
    frozen = json.loads(blob(repo, DATASET, "reports/evidence/stage-12/manual-witnesses.json"))[buffer]
    b["observed_P0_projection"] = projection
    b["matches_historical_projection"] = {r["job"]: projection == r["projection"] for r in frozen}
    return {fib: f, airline: a, buffer: b, "circular_historical_counter_boundaries": historical_counters(repo, metrics)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("historical_repo", type=Path)
    parser.add_argument("stock_evidence", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    save(args.output, audit(args.historical_repo.resolve(), args.stock_evidence.resolve()))
