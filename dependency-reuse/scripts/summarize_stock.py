"""Archive stock output losslessly and derive the D0 property, query and timing tables offline."""
import argparse
import gzip
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from run_stock import BASE, ORDER, save, sha

STAT = re.compile(r"ClosureSolver finishes with (\d+) conflicts, (\d+) decisions, and (\d+) propagations\. "
                  r"(\d+) theory propagations and (\d+) cycles included\.")
CO = re.compile(r"Attempts to add co clauses: (\d+)\. Added co clauses: (\d+)\. Total co pairs: (\d+)\.")
COUNTERS = ("sat_conflicts", "decisions", "sat_propagations", "theory_propagations", "theory_cycle_conflicts",
            "dynamic_co_batches_added", "dynamic_co_pairs_added")


def ui_and_diagnostics(raw):
    # Stock writes plain diagnostics between complete JSON UI objects, even before the
    # comma introducing the next object. Decode whole objects (including nested traces).
    raw = raw.strip()
    begin = re.match(r"\[\s*(?=\{)", raw)
    if begin is None or not raw.endswith("]"):
        raise ValueError("incomplete stock JSON UI envelope")
    separator = re.compile(r",\n  (?=\{)")
    decoder = json.JSONDecoder()
    objects, diagnostics = [], []
    pos = begin.end()
    while True:
        obj, end = decoder.raw_decode(raw, pos)
        if not isinstance(obj, dict):
            raise ValueError("non-object in stock UI")
        objects.append(obj)
        next_item = separator.search(raw, end)
        diagnostics.append(raw[end:next_item.start() if next_item else -1])
        if next_item is None:
            break
        pos = next_item.end()
    if "program" not in objects[0] or "cProverStatus" not in objects[-1]:
        raise ValueError("stock UI header or final status missing")
    return objects, "\n".join(diagnostics)


def queries(messages, native):
    calls = [m for m in messages if m.startswith("Solving with ")]
    outcomes = [m for m in messages if m.startswith(("SAT checker:", "SAT checker inconsistent:",
                                                      "got FALSE as assumption:"))]
    solver_times = [float(m.removeprefix("Runtime Solver: ").removesuffix("s"))
                    for m in messages if m.startswith("Runtime Solver: ")]
    sizes = [re.fullmatch(r"(\d+) variables, (\d+) clauses", m) for m in messages]
    sizes = [list(map(int, m.groups())) for m in sizes if m]
    snapshots, co = STAT.findall(native), CO.findall(native)
    if len(outcomes) != len(calls) or len(sizes) != len(calls) or len(snapshots) != len(co):
        raise ValueError("incomplete SAT adapter or Closure query records")
    # This baseline has one property_decider.solve per adapter query.
    if len(solver_times) != len(calls) or any(c != "Solving with Deagle's Closure Solver" for c in calls):
        raise ValueError("unexpected decision procedure/query boundaries")
    result = []
    finished = 0
    previous = dict.fromkeys(COUNTERS, 0)
    for i, msg in enumerate(outcomes):
        q = dict(query=i + 1, adapter_message=msg, reported_variables=sizes[i][0],
                 live_clauses=sizes[i][1], property_decider_solve_s=solver_times[i],
                 early_adapter_return=not msg.startswith("SAT checker:"), native_cumulative=None,
                 native_delta_from_previous_snapshot=None, adapter_entry_to_exit_delta=None,
                 restarts=None, search_only_s=None)
        if not q["early_adapter_return"]:
            if finished >= len(snapshots):
                raise ValueError("missing ClosureSolver::solve_ completion")
            numbers = list(map(int, snapshots[finished] + co[finished]))
            current = dict(zip(COUNTERS, numbers[:-1]))
            delta = {k: v - previous[k] for k, v in current.items()}
            if any(value < 0 for value in delta.values()):
                raise ValueError("native cumulative counter decreased")
            q.update(native_cumulative=current, native_delta_from_previous_snapshot=delta,
                     co_pairs_in_graph_at_return=numbers[-1])
            previous = current
            finished += 1
        result.append(q)
    if finished != len(snapshots):
        raise ValueError("unmatched native solve completion")
    return result


def interpret(meta, raw):
    ui, native = ui_and_diagnostics(raw)
    groups = [o["result"] for o in ui if "result" in o]
    totals = [o["cProverStatus"] for o in ui if "cProverStatus" in o]
    if len(groups) != 1 or len(totals) != 1:
        raise ValueError("missing or ambiguous native result")
    total, rows = totals[0], groups[0]
    if (meta["exit_code"], total) not in ((0, "success"), (10, "failure"), (5, "inconclusive")):
        raise ValueError("native exit and overall result disagree")
    by_id = {p["property"]: p for p in rows}
    if len(rows) != len(by_id) or meta["target"] not in by_id:
        raise ValueError("duplicate native property or missing target")
    if total == "success" and any(p["status"] != "SUCCESS" for p in rows):
        raise ValueError("successful overall result has unresolved properties")
    failures = {k: p for k, p in by_id.items() if p["status"] == "FAILURE"}
    for k, p in failures.items():
        trace = p.get("trace", [])
        if not trace or (trace[-1].get("stepType"), trace[-1].get("property")) != ("failure", k):
            raise ValueError(f"missing final witness for {k}")
    messages = [o["messageText"] for o in ui if "messageText" in o]
    loops = defaultdict(list)
    for msg in messages:
        match = re.fullmatch(r"Unwinding loop (\S+) iteration (\d+) (.+)", msg)
        if match:
            loop, iteration, location = match.groups()
            loops[f"{loop} {location}"].append(int(iteration))
    uw = [p for p in rows if "unwind" in (p["property"] + " " + p["description"]).lower()]
    bound_messages = [m for m in messages if m.lower().startswith("not unwinding") or
                      "no unwinding assertion" in m.lower()]
    timers = defaultdict(list)
    for m in messages:
        t = re.fullmatch(r"Runtime (.+): ([-+\d.eE]+)s", m)
        if t:
            timers[t[1]].append(float(t[2]))
    qs = queries(messages, native)
    target_status = by_id[meta["target"]]["status"]
    if any(p["status"] != "SUCCESS" for p in uw) or bound_messages:
        classification = "INCOMPLETE_UNWINDING"
    elif target_status == "FAILURE":
        classification = "VIOLATION"
    elif target_status == "SUCCESS" and total == "success":
        classification = "BOUNDED_PASS"
    else:
        classification = "UNKNOWN"
    return dict(classification=classification, cProverStatus=total, target_status=target_status,
                properties=[{k: v for k, v in p.items() if k != "trace"} for p in rows],
                trace_step_counts={k: len(p["trace"]) for k, p in failures.items()},
                unwinding_property_ids=[p["property"] for p in uw], unwinding_iterations=dict(loops),
                unwinding_stop_or_warning=bound_messages, enabled_unwinding_assertions="--unwinding-assertions" in meta["argv"],
                vcc_messages=[m for m in messages if "VCC(s)" in m],
                adapter_query_count=len(qs), closure_completion_count=len(STAT.findall(native)),
                queries=qs, native_timers_s=dict(timers),
                warnings=[o["messageText"] for o in ui if o.get("messageType") == "WARNING"],
                native_warning_lines=[s for s in native.splitlines() if s.startswith("WARNING:")]), failures


def read_stream(directory, name):
    p = directory / name
    return p.read_bytes() if p.is_file() else gzip.decompress(p.with_suffix(".gz").read_bytes())


def archive(source, destination):
    cases = json.loads((BASE / "bench/manifest.json").read_bytes())
    plan = json.loads((source / "plan.json").read_bytes())
    order = [(r["case"], r["side"]) for r in plan["order"]]
    if order != [(name, side) for name in ORDER for side in cases[name]["inputs"]]:
        raise ValueError("plan does not contain the complete fixed cohort in order")
    if sha(BASE / "bench/manifest.json") != plan["input_lock_sha256"]:
        raise ValueError("input lock differs from measured lock")
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "plan.json").write_bytes((source / "plan.json").read_bytes())
    results, traces = [], {}
    for name, side in order:
        key = f"{name}/{side}"
        src, dest = source / key, destination / key
        dest.mkdir(parents=True)
        spec = cases[name]
        meta = json.loads((src / "run.json").read_bytes())
        expect = {k: spec["files_sha256"][v] for k, v in spec["inputs"][side].items()}
        if ((meta["case"], meta["side"], meta["target"]) != (name, side, spec["target"]) or
                meta["input_sha256"] != expect or meta["argv"][1:] != spec["argv"] or
                meta["limits"] != spec["limits"] or meta["binary_sha256"] != plan["binary_sha256"] or
                meta["env"] != plan["env"] or meta["cpu_affinity"] != plan["cpu_affinity"]):
            raise ValueError(f"command, input or stock identity differs from plan: {key}")
        (dest / "run.json").write_bytes((src / "run.json").read_bytes())
        streams = {}
        for n in ("stdout", "stderr"):
            data = read_stream(src, n)
            if hashlib.sha256(data).hexdigest() != meta[n + "_sha256"]:
                raise ValueError(f"damaged {n}: {key}")
            (dest / (n + ".gz")).write_bytes(gzip.compress(data, mtime=0))
            streams[n] = data.decode("utf-8", errors="replace")
        row = {k: meta[k] for k in ("case", "side", "target", "exit_code", "timed_out", "wall_ns",
                                     "user_s", "system_s", "peak_rss_kib")}
        if meta["timed_out"]:
            row["classification"] = "TIMEOUT"
        elif meta["exit_code"] not in (0, 5, 10):
            oom = re.search(r"out of memory|bad_alloc|cannot allocate memory", "\n".join(streams.values()), re.I)
            row["classification"] = "OOM" if oom else "ERROR"
        else:
            try:
                interpreted, failures = interpret(meta, streams["stdout"])
                row.update(interpreted)
                if failures:
                    traces[key] = failures
            except (ValueError, KeyError, IndexError) as exc:
                row.update(classification="EVIDENCE_ERROR", reason=str(exc))
        results.append(row)
    save(destination / "metrics.json", results)
    (destination / "counterexamples.json.gz").write_bytes(
        gzip.compress((json.dumps(traces, indent=2) + "\n").encode(), mtime=0))
    save(destination / "sha256.json",
         {p.relative_to(destination).as_posix(): sha(p) for p in sorted(destination.rglob("*")) if p.is_file()})
    for r in results:
        print(r["case"], r["side"], r["classification"], r.get("reason", ""))
    return results


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("raw_or_archived_run", type=Path)
    cli.add_argument("new_output", type=Path)
    args = cli.parse_args()
    rows = archive(args.raw_or_archived_run, args.new_output)
    if any(r["classification"] not in ("VIOLATION", "BOUNDED_PASS") for r in rows):
        raise SystemExit(1)
