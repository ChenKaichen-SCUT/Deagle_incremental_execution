"""Prepare the live first-query delta and select verified-origin P0 births by reverse reachability."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from d1_identity import Keys, Model, load_rows
from d41_identity import pair_sites
from diff_d1 import compare_theory, digest, one_var_table
from prepare_d3 import facts

SCHEMA = "Deagle-SC-D4-library-v1"
RULES = "D3-v1/5f5bb7b5/distinct-competition"
TOOL_FILES = ("select", "boolean-diff", "d4_prepare.py", "d1_identity.py", "d1_theory.py",
              "diff_d1.py", "prepare_d3.py", "d41_identity.py")
RULES41="SC-triplet-v1/distinct-forward-orders/RF/active-competitor"
POLICIES=("none","boolean","mixed","theory","all","short")


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def check_library(lib, binary, tools, *, preflight=False):
    receipt = lib / "receipt.json"
    if (lib/"receipt.sha256").read_text().strip() != digest(receipt):
        raise ValueError("P0 receipt checksum")
    r = json.loads(receipt.read_text())
    if (r["schema"] != SCHEMA or r["rules"] != (RULES41 if r.get("triplets") else RULES) or r["native_sha256"] != digest(binary)
            or r["exit_code"] not in (0,10) or not r["sources"]):
        raise ValueError("incompatible P0 producer, scope or rules")
    if set(r["library_sha256"]) != {"model.tsv","proof.bin"}:
        raise ValueError("incomplete P0 library")
    for name, expected in r["library_sha256"].items():
        if not preflight and digest(lib/name) != expected:
            raise ValueError("P0 checksum mismatch for "+name)
    if r["tool_sha256"] != {f:digest(tools/f) for f in TOOL_FILES}:
        raise ValueError("incompatible mapping or selection tools")
    with (lib/"proof.bin").open("rb") as f:
        tag = f.read(8)
        f.seek(-8, 2)
        end = f.read()
    expected=b"DEAGD"+(b"C" if r.get("compact") else b"3")+bytes([2 if r.get("triplets") else 1,0])
    if tag!=expected or end!=r["exit_code"].to_bytes(4,"little")+(b"ENDC" if r.get("compact") else b"END3"):
        raise ValueError("incomplete or incompatible native proof")
    return r


def policies(out,policy):
    if policy not in POLICIES:raise ValueError("unknown D4.1 import policy")
    pool=out/"eligible.tsv"
    (out/"selected.tsv").rename(pool)
    with pool.open() as f:
        magic,variables,total=f.readline().split()
        rows=[l for l in f if l.strip()]
    if magic!="D4-selected-v1" or len(rows)!=int(total):raise ValueError("invalid eligibility pool")
    names={"B":"boolean","M":"mixed","T":"theory"}
    take=[]
    for row in rows:
        _,kind,size,*_=row.split()
        if policy=="all" or policy==names[kind] or (policy=="short" and int(size)<=4):take.append(row)
    (out/"selected.tsv").write_text(f"{magic}\t{variables}\t{len(take)}\n"+"".join(take))
    save(out/"policy.json",dict(policy=policy,eligible=len(rows),chosen=len(take),pool_sha256=digest(pool)))


def prepare(lib, out, tools):
    timings = {}
    start = time.monotonic_ns()
    # The caller is the live native process suspended in at_root_boundary.
    receipt = check_library(lib, Path(f"/proc/{os.getppid()}/exe"), tools)
    old, new = lib/"model.tsv", out/"boundary.tsv"
    keys = Keys()
    control=out/"control.json"
    cfg=json.loads(control.read_text()) if control.exists() else {}
    improved=cfg.get("mapping")=="d41"
    focused=cfg.get("diff")=="focused"
    if improved and not receipt.get("identities"):raise ValueError("missing source site/layout witnesses")
    if focused and not receipt.get("compact"):raise ValueError("focused matching needs a compact library")
    raw=[load_rows(old,capture_graph=focused),load_rows(new)]
    paired=pair_sites(*raw,keys) if improved else (None,None)
    m0=Model(old,keys,True,recorded_queries=True,records=raw[0],site_pairs=paired[0])
    m1=Model(new,keys,True,live_boundary=True,records=raw[1],site_pairs=paired[1])
    if m0.rows["END"] != [(str(receipt["exit_code"]),)] or m0.rows["K"] != m1.rows["K"]:
        raise ValueError("different P0 completion or native SC configuration")
    t = time.monotonic_ns()
    timings["validate_and_read_models_ns"] = t-start
    delta = out/"delta"
    delta.mkdir()
    anchors = [delta/"P0.anchors",delta/"P1.anchors"]
    m0.write_anchors(m1,anchors[0])
    m1.write_anchors(m0,anchors[1])
    mode=("--d41-map-only" if improved else "--d41-old-map-only") if focused else ("--d41-map" if improved else "--d4-boundary")
    subprocess.run([tools/"boolean-diff",old,new,*anchors,delta,mode],check=True)
    maps, variables = one_var_table(delta/"variables.tsv",[m0,m1])
    after = time.monotonic_ns()
    timings["anchors_and_boolean_delta_ns"] = after-t
    old_rows=[] if focused else None
    theory=compare_theory([m0,m1],maps,delta,old_rows=old_rows)
    facts(old,delta,delta/"declarations.txt",graph_lines=raw[0]["_GRAPH"] if focused else None,declaration_rows=old_rows)
    before_select = time.monotonic_ns()
    timings["theory_delta_ns"] = before_select-after
    subprocess.run([tools/"select",lib/"proof.bin",old,delta,delta/"declarations.txt",
                    str(m0.nvars),str(m1.nvars),out,*([new] if focused else [])],check=True)
    if cfg:policies(out,cfg["policy"])
    timings["selector_process_ns"] = time.monotonic_ns()-before_select
    save(out/"delta.json",dict(P0_receipt_sha256=digest(lib/"receipt.json"),P1_boundary_sha256=digest(new),
        variables=variables,theory=theory,first_query=True,selection=cfg.get("policy","all"),
        interval_pairs=len(paired[0]) if improved else 0,focused=focused,mapping=cfg.get("mapping","d4"),
        timings_ns=timings))
    # Publish the batch only after the selector, receipt binding and delta output completed.
    (out/"selected.tsv").rename(out/"ready.tsv")


if __name__=="__main__":
    if len(sys.argv)!=4:raise SystemExit("usage: d4_prepare.py LIBRARY LIVE_OUT TOOLS")
    prepare(*(Path(arg).resolve() for arg in sys.argv[1:]))
