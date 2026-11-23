#!/usr/bin/env python3
"""Verify the published Stage 4 evidence offline with the Python standard library."""
import gzip
import hashlib
import json
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from incdeagle.adapters.deagle import classify
from incdeagle.model.repeat import phase_digest

EVIDENCE = ROOT / "reports/evidence/stage-04"
PHASES = ("goto", "raw_ssa", "sc_input", "full_model")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    index = json.loads((EVIDENCE / "archive.json").read_bytes())
    archive = EVIDENCE / index["archive"]
    data = archive.read_bytes()
    require(len(data) == index["bytes"] and hashlib.sha256(data).hexdigest() == index["sha256"],
            "The published archive differs from its index")
    results = json.loads((EVIDENCE / "acceptance.json").read_bytes())["cases"]
    lock = json.loads((ROOT / "configs/stage04.lock.json").read_bytes())
    with tarfile.open(archive, "r:gz") as runs:
        require(sorted(runs.getnames()) == sorted(index["files"]), "Archive member list differs")
        for member in runs:
            require(member.isfile(), member.name)
            content = runs.extractfile(member).read()
            require(hashlib.sha256(content).hexdigest() == index["files"][member.name], member.name)

        for name, result in results.items():
            def raw(relative):
                return runs.extractfile("verification/" + name + "/" + relative).read()

            def document(relative):
                return json.loads(raw(relative))

            session = document("pair/session.json")
            require(session["tool"]["development_sha256"] == lock["development_sha256"], name)
            expected = json.loads((EVIDENCE / "cases" / (name + ".json")).read_bytes())
            for phase in PHASES:
                online = phase_digest(document("pair/candidate/" + phase + ".json"))
                full = phase_digest(document("full/" + phase + ".json"))
                require(online == full == expected["phase_digests"][phase]["full"], name + "/" + phase)

            for version in ("old", "candidate"):
                independent = document("independent/" + version + "/run.json")
                require(independent["deagle_sha256"] == lock["baseline_sha256"], name)
                oracle = independent["runs"]["verify"]
                phi = {"id": independent["target"], "source": independent["target_source"]}
                base, _ = classify(gzip.decompress(raw("independent/" + version + "/" + oracle["document"])),
                                   oracle["exit_code"], phi)
                online, target = classify(raw("pair/" + version + "/result.json"), session[version + "_exit"], phi)
                require(online == base == session[version], name + "/" + version)
                require(len(target.get("trace", [])) == session[version + "_trace_steps"], name + "/trace")

            visits = document("full/visits.json")
            full_trace = [{key: row[key] for key in ("function", "pc", "thread")} for row in visits]
            skipped, executed = result["native_skipped"], result["native_executed"]
            require(len(full_trace) == skipped + executed, name + "/full dispatches")
            if session["path"] == "incremental":
                native = document("pair/candidate/native-stats.json")
                old = document("pair/old/native-stats.json")["executed_dispatches"]
                require(native["checkpoint_used"] and native["reused_prefix_symex_steps"] == skipped > 0, name)
                active = native["executed_dispatches"]
                require(len(active) == native["executed_symex_steps"] == executed, name + "/native dispatches")
                require(old[:skipped] + active == full_trace, name + "/restored trace")
                require(native["sc_counters"] == result["sc"] and
                        native["sc_counters"]["read_bundles_reused"] > 0, name + "/read fragments")
            else:
                require(skipped == 0 and session["fallback_reason"] == result["fallback_reason"], name)
                require(document("pair/candidate/metrics.json")["symbolic_instruction_dispatches"] == executed, name)
            print(f"{name}: full {len(full_trace)}, skipped {skipped}, executed {executed}, {result['candidate']}")
    print(f"Verified {len(index['files'])} archive members and four native model phases per candidate.")


if __name__ == "__main__":
    main()
