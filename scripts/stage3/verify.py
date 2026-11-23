#!/usr/bin/env python3
"""Rebuild eight version snapshots with the locked baseline and two fresh full sessions."""
import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.stage2.check_case import capture, check, load_case
from scripts.stage3.session import BINARY, CASES, OPS
from incdeagle.adapters.deagle import classify
from incdeagle.model.identity import file_sha, read, save
from incdeagle.model.repeat import phase_digest

SCHEMA = read(ROOT / "schemas/stage3-model.schema.json")
PHASES = {"parse_goto", "symbolic_execution", "symex_cleanup", "event_constraints", "cnf_and_graph",
          "goal_conversion", "solve", "result_output", "equation_export"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_schema(obj, definition):
    schema = {"$ref": "#/definitions/" + definition, "definitions": SCHEMA["definitions"]}
    jsonschema.Draft7Validator(schema).validate(obj)


def run_session(case, dest, commands=OPS, expect_success=True):
    transcript = dest.with_suffix(".jsonl")
    log = dest.with_suffix(".stderr")
    cmd = [sys.executable, "-B", str(ROOT / "scripts/stage3/session.py"), case, "--out", str(dest)]
    with log.open("w") as err, transcript.open("w") as proto:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, stderr=err)
        try:
            stdin = "".join(json.dumps({"op": k}) + "\n" for k in commands)
            # Each native build/verification also enforces the case timeout at its gate.
            stdout, _ = proc.communicate(stdin, timeout=1250)
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        rows = [json.loads(line) for line in stdout.splitlines()]
        for i, response in enumerate(rows):
            request = {"op": commands[i]} if i < len(commands) else None
            print(json.dumps({"request": request, "response": response}), file=proto)
    if expect_success:
        require(proc.returncode == 0 and [r["op"] for r in rows] == list(OPS), f"Protocol failed: {transcript}")
        for i, row in enumerate(rows):
            expected_workers = set() if i == 0 else ({"old"} if i < 4 else {"old", "candidate"})
            require(set(row["workers"]) == expected_workers, "Missing live model holder")
            require(all(w["alive"] == (i != 7) for w in row["workers"].values()), "Model lifetime mismatch")
        for role in ("old", "candidate"):
            require(len({r["workers"][role]["pid"] for r in rows if role in r["workers"]}) == 1, "Holder PID changed")
        require(rows[0]["memory_max_bytes"] == 21474836480, "Unexpected cgroup")
    else:
        require(proc.returncode != 0 and rows and "error" in rows[-1], "Malformed protocol was accepted")
    pids = {v["pid"] for r in rows for v in r.get("workers", {}).values()}
    require(all(not Path("/proc", str(pid)).exists() for pid in pids), "Native holder survived session exit")
    return rows


def structure(model, folder, phi):
    check_schema(model, "model")
    counts = model["counts"]
    source_map = model["mappings"]["sources"]
    for event in model["events"]:
        require(event["key"]["source"] in source_map and bool(source_map[event["key"]["source"]]["locations"]),
                "Event lacks native source provenance")
    phases = [read(folder / (label + ".json")) for label in ("raw_ssa", "sc_input", "full_model")]
    require(all(not doc["oc_edges"] for doc in phases[:2]) and bool(phases[2]["oc_edges"]), "Wrong observation phases")
    final = counts["full_model"]
    require(final["events"] == len(model["events"]) and len(phases[2]["steps"]) == final["steps"], "Bad counts")
    require(all(final["edge_kinds"].get(k, 0) > 0 for k in ("rf", "po", "apo")), "Missing SC edges")
    require(all(final["constraint_comments"].get(k, 0) > 0 for k in ("rf-val", "rf-some")), "Missing RF semantics")
    require(phi == model["target"] and phi in final["properties"], "Missing model property")
    require(all(child in model["typed_nodes"] for node in model["typed_nodes"].values()
                for child in list(node["fields"].values()) + node["operands"] if child), "Unresolved expression DAG")
    metrics = read(folder / "metrics.json")
    require(set(metrics["phase_nanoseconds"]) == PHASES and all(n > 0 for n in metrics["phase_nanoseconds"].values())
            and metrics["symbolic_instruction_dispatches"] == counts["symbolic_instruction_dispatches"], "Bad timers/counters")


def partition(diff, old, candidate):
    require(len(diff["events_changed"]) + len(diff["events_retained"]) + len(diff["events_removed"]) == len(old["events"]),
            "Old event partition is incomplete")
    require(len(diff["events_changed"]) + len(diff["events_retained"]) + len(diff["events_added"]) == len(candidate["events"]),
            "Candidate event partition is incomplete")
    retained = sum(x["count"] for x in diff["constraints_retained"])
    require(retained + len(diff["constraints_removed"]) == len(old["fragments"]) and
            retained + len(diff["constraints_added"]) == len(candidate["fragments"]), "Formula multiset mismatch")


def unobserved(case, role, folder, baseline):
    task, gamma, phi = load_case(case)
    folder.mkdir(parents=True)
    shutil.copyfile(case / task["old_source" if role == "old" else "candidate_source"], folder / "program.c")
    shutil.copyfile(case / "harness.c", folder / "harness.c")
    cmd = [BINARY, *gamma["source_argv"], *gamma["verification_output"], "harness.c"]
    run = capture(folder, "verify", cmd, cwd=folder, environment={"INCDEAGLE_JSON_OUTPUT": str(folder / "result.json")})
    result, _ = classify((folder / "result.json").read_bytes(), run["exit_code"], phi)
    require(all(result[k] == baseline[k] for k in result) and
            all(file_sha(folder / k) == baseline["input_sha256"][k] for k in ("harness.c", "program.c"))
            and not (folder / "metrics.json").exists(), "Uninstrumented full path disagrees")
    save(folder / "run.json", {"result": result, "process": run})
    return {"result": result["classification"], "exit": run["exit_code"], "wall_seconds": run["wall_seconds"]}


def replay(output):
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    summary = {"started_utc": datetime.now(timezone.utc).isoformat(), "cases": {}, "sessions": 0, "baseline_runs": 0,
               "development_full_runs": 0, "development_observer_off_runs": 0, "deepseek_calls": 0,
               "mode": "full", "model_reuse": False}
    for name in ("batch_total", "threshold_guard", "split_counter", "partial_counter"):
        case = CASES[name]
        dest = output / name
        dest.mkdir()
        independent = {role: check(case, role, dest / "baseline" / role) for role in ("old", "candidate")}
        summary["baseline_runs"] += len(independent)
        for role, ref in independent.items():
            if ref["classification"] == "VIOLATION":
                tag = "0" if role == "old" else "1"
                witness = read(dest / "baseline" / role / ("cex" + tag + ".json"))
                require(witness["p" + tag + "_sha256"] == ref["input_sha256"]["program.c"],
                        "Trace belongs to a different source snapshot")
        plain = {role: unobserved(case, role, dest / "observer-off" / role, ref) for role, ref in independent.items()}
        summary["development_observer_off_runs"] += len(plain)
        first, differences = {}, []
        for run in ("build1", "build2"):
            sess = dest / run
            rows = run_session(name, sess)
            summary["sessions"] += 1
            models = {}
            for role in ("old", "candidate"):
                d = sess / role
                s, m, v = (read(d / f) for f in ("summary.json", "model.json", "manifest.json"))
                models[role] = m
                summary["development_full_runs"] += 1
                ref = independent[role]
                expected = "VIOLATION" if role == "old" or name == "partial_counter" else "NO_VIOLATION_WITHIN_BOUND"
                require(ref["classification"] == expected and all(s["result"][k] == ref[k] for k in
                        ("classification", "target", "target_source", "properties", "unwinding_properties", "native_overall")),
                        name + " " + role + " disagrees with reference")
                require(rows[-1]["exit_codes"][role] == s["metrics"]["exit_code"] == ref["runs"]["verify"]["exit_code"],
                        "Exit code mismatch")
                require(file_sha(d / "program.c") == ref["input_sha256"]["program.c"] and
                        file_sha(d / "harness.c") == ref["input_sha256"]["harness.c"], "Different actual inputs")
                check_schema(v, "manifest")
                structure(m, d, ref["target"])
                require("Use Deagle's closure solver" in (d / "diagnostic.stdout").read_text() and
                        "Set Deagle closure solver's graph" in (d / "diagnostic.stdout").read_text(), "Wrong backend")
                replay_hashes = {stage: phase_digest(read(d / (stage + ".json")))
                                 for stage in ("goto", "raw_ssa", "sc_input", "full_model")}
                replay_hashes["native_visits"] = file_sha(d / "visits.json")
                record = {"model_digest": m["structure_sha256"], "version": v["version_sha256"],
                          "same_input_phase_digests": replay_hashes,
                          "context": v["context_sha256"], "counts": m["counts"], "classification": expected,
                          "target": ref["target"], "source": ref["target_source"], "trace_steps": s["result"]["trace_steps"],
                          "baseline_verify_wall_s": ref["runs"]["verify"]["wall_seconds"],
                          "observer_off": plain[role],
                          "phase_nanoseconds": s["metrics"]["phase_nanoseconds"]}
                if run == "build1":
                    first[role] = record
                else:
                    for k in ("model_digest", "version", "context", "counts", "same_input_phase_digests"):
                        require(first[role][k] == record[k], f"{name}/{role} repeated build differs in {k}")
                    first[role]["repeat_model_digest"] = record["model_digest"]
                    first[role]["repeat_phase_digests"] = replay_hashes
                    first[role]["repeat_phase_nanoseconds"] = record["phase_nanoseconds"]
            diff = read(sess / "delta.json")
            check_schema(diff, "delta")
            partition(diff, models["old"], models["candidate"])
            require(not diff["checkpoint_used"] and diff["old_version"] != diff["candidate_version"], "Wrong version mode")
            if name == "batch_total":
                writes = [e for e in models["candidate"]["events"] if e["bucket"] == "shipped_units" and e["key"]["role"] == "write"]
                require(any(c["id"] == e["id"] and "value" in c["reasons"] for c in diff["events_changed"] for e in writes),
                        "Same write identity did not detect changed RHS")
            if name == "partial_counter":
                require("counter" in diff["affected_address_buckets"] and diff["events_changed"], "Missing partial-repair impact")
            differences.append(file_sha(sess / "delta.json"))
        require(differences[0] == differences[1], name + " repeated delta differs")
        summary["cases"][name] = {"versions": first, "same_delta_sha256": differences[0],
                                  "events": {k.removeprefix("events_"): len(v) for k, v in diff.items() if k.startswith("events_")},
                                  "constraints": {"added": len(diff["constraints_added"]), "removed": len(diff["constraints_removed"]),
                                                  "retained": sum(r["count"] for r in diff["constraints_retained"])},
                                  "mapping": diff["source_mapping_summary"]}
        save(output / "acceptance.json", summary)
    for name, ops in (("order", ("LOAD_OLD", "VERIFY_OLD")), ("eof", ("LOAD_OLD", "BUILD_OLD"))):
        rows = run_session("batch_total", output / ("protocol-" + name), ops, expect_success=False)
        summary["protocol_" + name] = rows[-1]
    summary["all_native_holders_exited"] = True
    summary["wall_seconds"] = round(time.monotonic() - started, 4)
    summary["finished_utc"] = datetime.now(timezone.utc).isoformat()
    save(output / "acceptance.json", summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    replay(parser.parse_args().out.resolve())
