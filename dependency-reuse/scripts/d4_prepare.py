"""Prepare the live first-query delta and select verified-origin P0 births by reverse reachability."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from d1_identity import Keys, Model
from diff_d1 import compare_theory, digest, one_var_table
from prepare_d3 import facts

SCHEMA = "Deagle-SC-D4-library-v1"
RULES = "D3-v1/5f5bb7b5/distinct-competition"
TOOL_FILES = ("select", "boolean-diff", "d4_prepare.py", "d1_identity.py", "d1_theory.py",
              "diff_d1.py", "prepare_d3.py")


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def check_library(lib, binary, tools):
    receipt = lib / "receipt.json"
    if (lib/"receipt.sha256").read_text().strip() != digest(receipt):
        raise ValueError("P0 receipt checksum")
    r = json.loads(receipt.read_text())
    if (r["schema"] != SCHEMA or r["rules"] != RULES or r["native_sha256"] != digest(binary)
            or r["exit_code"] not in (0,10) or not r["sources"]):
        raise ValueError("incompatible P0 producer, scope or rules")
    if set(r["library_sha256"]) != {"model.tsv","proof.bin"}:
        raise ValueError("incomplete P0 library")
    for name, expected in r["library_sha256"].items():
        if digest(lib/name) != expected:
            raise ValueError("P0 checksum mismatch for "+name)
    if r["tool_sha256"] != {f:digest(tools/f) for f in TOOL_FILES}:
        raise ValueError("incompatible mapping or selection tools")
    with (lib/"proof.bin").open("rb") as f:
        tag = f.read(8)
        f.seek(-8, 2)
        end = f.read()
    if tag!=b"DEAGD3\x01\0" or end!=r["exit_code"].to_bytes(4,"little")+b"END3":
        raise ValueError("incomplete or incompatible native proof")
    return r


def prepare(lib, out, tools):
    timings = {}
    start = time.monotonic_ns()
    # The caller is the live native process suspended in at_root_boundary.
    receipt = check_library(lib, Path(f"/proc/{os.getppid()}/exe"), tools)
    old, new = lib/"model.tsv", out/"boundary.tsv"
    keys = Keys()
    m0 = Model(old, keys, True, recorded_queries=True)
    m1 = Model(new, keys, True, live_boundary=True)
    if m0.rows["END"] != [(str(receipt["exit_code"]),)] or m0.rows["K"] != m1.rows["K"]:
        raise ValueError("different P0 completion or native SC configuration")
    t = time.monotonic_ns()
    timings["validate_and_read_models_ns"] = t-start
    delta = out/"delta"
    delta.mkdir()
    anchors = [delta/"P0.anchors",delta/"P1.anchors"]
    m0.write_anchors(m1,anchors[0])
    m1.write_anchors(m0,anchors[1])
    subprocess.run([tools/"boolean-diff",old,new,*anchors,delta,"--d4-boundary"],check=True)
    maps, variables = one_var_table(delta/"variables.tsv",[m0,m1])
    after = time.monotonic_ns()
    timings["anchors_and_boolean_delta_ns"] = after-t
    theory = compare_theory([m0,m1],maps,delta)
    facts(old, delta, delta/"declarations.txt")
    before_select = time.monotonic_ns()
    timings["theory_delta_ns"] = before_select-after
    subprocess.run([tools/"select",lib/"proof.bin",old,delta,delta/"declarations.txt",
                    str(m0.nvars),str(m1.nvars),out],check=True)
    timings["selector_process_ns"] = time.monotonic_ns()-before_select
    save(out/"delta.json",dict(P0_receipt_sha256=digest(lib/"receipt.json"),P1_boundary_sha256=digest(new),
        variables=variables,theory=theory,first_query=True,selection="all surviving translatable final births in creation order",
        timings_ns=timings))
    # Publish the batch only after the selector, receipt binding and delta output completed.
    (out/"selected.tsv").rename(out/"ready.tsv")


if __name__=="__main__":
    if len(sys.argv)!=4:raise SystemExit("usage: d4_prepare.py LIBRARY LIVE_OUT TOOLS")
    prepare(*(Path(arg).resolve() for arg in sys.argv[1:]))
