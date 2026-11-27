"""Locked four-case cohort. The historical SC/ILP32 case has its own verdict and limit."""
import json
from run_stock import BASE
from diff_d1 import digest


def load():
    specs=json.loads((BASE/"bench/manifest.json").read_text())
    stage=json.loads((BASE/"configs/d42-plan.json").read_text())
    name="fib-snapshot-11";root=BASE/"bench"/name
    t=json.loads((root/"task.yaml").read_text())
    assert t["model"]=="ILP32" and digest(root/t["property"])==t["property_sha256"]
    hashes={v["file"]:v["sha256"] for v in t["sides"].values()}
    assert all(digest(root/f)==h for f,h in hashes.items())
    specs[name]=dict(target="reach_error.assertion.1",argv=t["argv"],files_sha256=hashes,
            inputs={side:{"program.i":t["sides"][label]["file"]} for side,label in (("P0","old"),("P1","new"))},
            limits=dict(timeout_seconds=t["limits"]["timeout_s"],memory_bytes=t["limits"]["memory_gib"]<<30))
    return {k:specs[k] for k in stage["cases"]}
