"""Verify PI-0 archived controls and census against pinned inputs, without running Deagle."""
import gzip
import json
import sys
from pathlib import Path

from frozen import CASES, RESEARCH, STOCK, TREE, UPSTREAM, blob, digest, require

root = Path(__file__).resolve().parents[1]
ev = root / "reports/evidence/pi0"


def read(path):
    return json.loads(path.read_bytes())


def verify(repo):
    index = read(ev / "files.json")
    present = {p.relative_to(ev).as_posix() for p in ev.rglob("*") if p.is_file()}
    require(present == set(index) | {"files.json"}, "missing or extra raw evidence")
    for name, h in index.items():
        data = (ev / name).read_bytes()
        require(len(data) == h["bytes"] and digest(data) == h["sha256"], name)

    plan = read(root / "configs/frozen-pairs.json")
    require(plan["research"] == RESEARCH and plan["upstream"] == UPSTREAM, "wrong plan")
    original = blob(repo, "reports/evidence/si1a/frozen-inputs.json")
    require(digest(original) == plan["reference_sha256"], "changed input lock")
    original = json.loads(original)
    scale = read(ev / "scale.json")["cases"]
    reference_rows = json.loads(blob(repo, "reports/evidence/si1a/frozen-model-fingerprints.json"))
    require(tuple(plan["cases"]) == CASES and set(scale) == set(CASES), "incomplete cohort")
    expected_arms = tuple(plan["comparators"])
    for i, case in enumerate(CASES):
        cfg = plan["cases"][case]
        for key in ("argv", "target", "limits", "staged", "role"):
            require(cfg[key] == original[case][key], case + " " + key)
        require(cfg["files_sha256"] == original[case]["files"], case + " file lock")
        for name, h in cfg["files_sha256"].items():
            require(digest(blob(repo, "bench/" + case + "/" + name)) == h, name)
        require(len(cfg["round_order"]) == 3, "missing round")
        for n, order in enumerate(cfg["round_order"]):
            shift = (i + n) % len(expected_arms)
            require(tuple(order) == expected_arms[shift:]+expected_arms[:shift], "round order")
        d = scale[case]
        require(digest(blob(repo, d["map_path"])) == d["map_sha256"], "signed mapping changed")
        for side, field in (("P0", "P0_epoch_plan"), ("P1", "P1_active_only")):
            m = d[side]
            require(digest(blob(repo, m["model"])) == m["compressed_sha256"], "model changed")
            ref = reference_rows[case][side]["rows"]
            require(sum(v["occurrences"] for v in m["scopes"].values()) == ref["C"], "input occurrences")
            require(ref["QUERY"] == ref["N"] == m["query_boundaries"] == 1 and
                    len(m["targets"]) == ref["TARGET"], "native query boundary")
            for tag in ("EDGE","GUARD","NODE","MEMBER","IN","OUT","CO"):
                require(m["installed_graph"].get(tag, 0) == ref.get(tag, 0), "graph " + tag)
            for v in m["scopes"].values():
                require(v["occurrences"] == v["unique"] + v["duplicate_occurrences"] +
                        v["true_or_tautological"], "canonical content count")
            total = sum(v["unique"] for v in m["scopes"].values()) + 2 + len(m["native_assumptions"])
            require(d[field]["assumptions"] == total, "single-version assumptions")
        fresh = d["P1_union_with_fresh_atoms"]
        union = d["P1_union_with_diagnostic_map"]
        require(fresh["assumptions"] - union["assumptions"] ==
                d["certified_shared_B"] - min(d[s]["scopes"]["B"]["empty"] for s in ("P0","P1")),
                "union cardinality")
        require(all(sum(d[k]["bytes"].values()) == d[k]["modeled_subtotal_bytes"] for k in
                    ("P0_epoch_plan","P1_active_only","P1_union_with_diagnostic_map","P1_union_with_fresh_atoms")),
                "layout subtotal")

    build = read(ev / "stock/build.json")
    require((build["source_commit"],build["source_tree"],build["binary_sha256"]) == (UPSTREAM,TREE,STOCK), "ELF lock")
    require(digest(gzip.decompress((ev / "stock/build.log.gz").read_bytes())) == build["build_log_sha256"], "make log")
    controls = read(ev / "stock/checks.json")
    require([r["case"]+"/"+r["side"] for r in controls["controls"]] == plan["PI0_stock_controls"], "smoke cohort")
    old = {(r["case"],r["side"]):r for r in json.loads(blob(repo,"reports/evidence/d0/stock/metrics.json"))}
    manifest = json.loads(blob(repo, "bench/manifest.json"))
    for row in controls["controls"]:
        case, side = row["case"], row["side"]
        folder = ev / "stock" / case / side
        meta, outcome = read(folder / "run.json"), read(folder / "result.json")
        baseline = old[case, side]
        spec = manifest[case]
        inputs = {k:spec["files_sha256"][v] for k,v in spec["inputs"][side].items()}
        require(meta["input_sha256"] == inputs and meta["argv"][1:] == spec["argv"] and
                meta["limits"] == spec["limits"] and meta["cpu_affinity"] == [0] and
                meta["binary_sha256"] == STOCK and meta["exit_code"] == baseline["exit_code"], "stock execution")
        for name in ("stdout","stderr"):
            require(digest(gzip.decompress((folder/(name+".gz")).read_bytes())) == meta[name+"_sha256"], name)
        for key in ("classification","target_status","trace_step_counts","unwinding_iterations","unwinding_property_ids",
                    "unwinding_stop_or_warning","enabled_unwinding_assertions"):
            require(outcome[key] == baseline[key], f"{case}/{side} {key}")
        require(outcome["queries"][0]["native_cumulative"] == baseline["queries"][0]["native_cumulative"], "stock trace")
    print("PASS: immutable inputs, four archived pairs, selector counts, three stock controls and raw evidence.")


if __name__ == "__main__":
    verify(Path(sys.argv[1]))
