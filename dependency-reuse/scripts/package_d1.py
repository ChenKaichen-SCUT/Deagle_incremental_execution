"""Verify and archive one named D1 cohort, with byte-level audit and raw receipts."""
import argparse
from collections import Counter
from itertools import groupby
import filecmp
import gzip
import hashlib
import json
from pathlib import Path
import shutil

from check_d1_delta import verify
from diff_d1 import digest
from run_d1 import CASES
from run_stock import BASE, save


def packed(src,dst):
    dst.parent.mkdir(parents=True,exist_ok=True)
    with src.open("rb") as rd, dst.open("xb") as wr, gzip.GzipFile(filename="",mode="wb",fileobj=wr,
                                                                   compresslevel=6,mtime=0) as gz:
        shutil.copyfileobj(rd,gz,1<<20)


def logical(x):
    if isinstance(x,dict): return {k:logical(v) for k,v in x.items() if k!="workingDirectory"}
    if isinstance(x,list): return [logical(v) for v in x]
    return x


def metrics(x):
    q = [{k:v for k,v in row.items() if k!="property_decider_solve_s"} for row in x["queries"]]
    return logical({**{k:x[k] for k in ("properties","cProverStatus","classification","target_status",
        "trace_step_counts","unwinding_property_ids","unwinding_iterations","unwinding_stop_or_warning",
        "enabled_unwinding_assertions","vcc_messages","adapter_query_count","closure_completion_count",
        "warnings","native_warning_lines")}, "queries":q})


def probe_hash(p):
    h = hashlib.sha256()
    count = 0
    with p.open("rb") as file:
        for b in file:
            count += 1
            h.update(b)
    return dict(sha256=h.hexdigest(), records=count, bytes=p.stat().st_size)


def observe_c(p):
    h = hashlib.sha256()
    with p.open("rb") as file:
        for line in file:
            if line.startswith(b"C\t"):
                _,scope,*lits = line.split()
                h.update(b" ".join([str(len(lits)).encode(),*lits])+b"\n")
    return h.hexdigest()


def trace_comparison(reference, witness):
    a, b = logical(reference), logical(witness)
    if a.keys()!=b.keys(): raise ValueError("counterexample property set changed")
    details = {}
    for prop, old in a.items():
        x, y = old["trace"], b[prop]["trace"]
        if len(x)!=len(y): raise ValueError("counterexample length changed")
        positions = [i for i,(u,v) in enumerate(zip(x,y)) if u!=v]
        spans = []
        canonical = lambda values: Counter(json.dumps(s,sort_keys=True) for s in values)
        for _, group in groupby(enumerate(positions),lambda pair:pair[1]-pair[0]):
            indexes = [index for _,index in group]
            left,right = ([steps[i] for i in indexes] for steps in (x,y))
            spans.append(dict(first_zero_based=indexes[0],last_zero_based=indexes[-1],
                              same_step_multiset=canonical(left)==canonical(right),
                              hidden_assignments=all(v.get("hidden") and v.get("stepType")=="assignment"
                                                     for v in left+right)))
        details[prop] = dict(total_steps=len(x),different_positions=len(positions),spans=spans,
                             visible_steps_equal=[v for v in x if not v.get("hidden")]==
                                                 [v for v in y if not v.get("hidden")])
    return details


def extended_audit(out,active):
    ref = json.load(gzip.open(BASE/"reports/evidence/d0/stock/counterexamples.json.gz"))
    receipts = json.loads((out/"comparison.json").read_text())
    target = out/"runs/probe_record"
    target.mkdir()
    shutil.copyfile(active/"plan.json",target/"plan.json")
    rows = []
    for receipt in receipts:
        case,side = receipt["case"],receipt["side"]
        relative = Path(case)/side
        src = active/relative
        dest = target/relative
        dest.mkdir(parents=True)
        shutil.copyfile(src/"run.json",dest/"run.json")
        for part in ("stdout","stderr","result.json"):
            packed(src/part,dest/(part+".gz"))
        state = dict(case=case,side=side,trace={},active_streams={},active_manifest_sha256=digest(src/"native.tsv"))
        reference = ref.get(f"{case}/{side}",{})
        stock_metrics = json.load(gzip.open(out/"runs/probe_stock"/relative/"result.json.gz"))[0]
        for mode in ("off","record","probe_stock","probe_dev","probe_record"):
            result,witness = json.load(gzip.open(out/"runs"/mode/relative/"result.json.gz"))
            if metrics(result)!=metrics(stock_metrics): raise ValueError("audited result changed: "+mode)
            comparison = trace_comparison(reference,witness)
            state["trace"][mode] = comparison
            if mode in ("off","probe_stock","probe_dev") and any(v["different_positions"] for v in comparison.values()):
                raise ValueError("disabled observer trace differs")
        for tag,expected in receipt["streams"].items():
            path = src/"work"/("audit-"+tag)
            actual = probe_hash(path)
            same = actual==expected
            state["active_streams"][tag] = dict(equal=same,**actual)
            if not same: packed(path,out/"audit-active"/relative/(tag+".gz"))
        rows.append(state)
    save(out/"trace-and-active.json",rows)


def save_index(out):
    index = {str(p.relative_to(out)):digest(p) for p in sorted(out.rglob("*"))
             if p.is_file() and p!=out/"sha256.json"}
    save(out/"sha256.json",index)
    return len(index)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("record","off","probe_stock","probe_dev","delta","tests","new_directory"):
        parser.add_argument(arg,type=Path)
    parser.add_argument("--active-probe",type=Path)
    args = parser.parse_args()
    out = args.new_directory.resolve()
    out.mkdir(parents=True,exist_ok=False)
    baseline = BASE/"reports/evidence/d0/stock"
    d0 = {(r["case"],r["side"]):r for r in json.loads((baseline/"metrics.json").read_text())}
    results = []
    modes = dict(record=args.record, off=args.off, probe_stock=args.probe_stock, probe_dev=args.probe_dev)
    for name,root in modes.items():
        target = out/"runs"/name
        target.mkdir(parents=True)
        shutil.copyfile(root/"plan.json",target/"plan.json")
    for case in CASES:
        pair = args.delta/case
        manifest = [args.record/case/side/"native.tsv" for side in ("P0","P1")]
        diff = json.loads((pair/"summary.json").read_text())
        if [digest(p) for p in manifest] != diff["native_sha256"]: raise ValueError("manifest changed")
        check = verify(pair,manifest)
        dest = out/"pairs"/case
        shutil.copytree(pair,dest)
        save(dest/"independent-check.json",check)
        for s, side in enumerate(("P0","P1")):
            ref = d0[case,side]
            row = dict(case=case,side=side,baseline_wall_s=ref["wall_ns"]/1e9,
                       properties={p["property"]:p["status"] for p in ref["properties"]},
                       warnings=len(ref["warnings"]),queries=ref["adapter_query_count"],modes={})
            for name,root in modes.items():
                src = root/case/side
                target = out/"runs"/name/case/side
                target.mkdir(parents=True)
                for part in ("stdout","stderr","result.json"):
                    packed(src/part,target/(part+".gz"))
                shutil.copyfile(src/"run.json",target/"run.json")
                run = json.loads((src/"run.json").read_text())
                data,witnesses = json.loads((src/"result.json").read_text())
                if run["timed_out"] or run["exit_code"]!=ref["exit_code"] or metrics(data)!=metrics(ref):
                    raise ValueError(f"property, warning or native counter mismatch: {name}/{case}/{side}")
                row["modes"][name] = dict(wall_s=run["wall_ns"]/1e9,peak_rss_kib=run["peak_rss_kib"],
                                          binary_sha256=run["binary_sha256"],exit_code=run["exit_code"])
            row["streams"] = streams = {}
            for tag in ("clauses","graph","vars","init"):
                relative = Path(case)/side/"work"/("audit-"+tag)
                a,b = (p/relative for p in (args.probe_stock,args.probe_dev))
                if not filecmp.cmp(a,b,shallow=False): raise ValueError(f"audit stream differs: {relative}")
                streams[tag] = probe_hash(a)
                packed(a,out/"audit"/case/side/(tag+".gz"))
            row["recorded_input_sha256"] = observe_c(manifest[s])
            if row["recorded_input_sha256"] != streams["clauses"]["sha256"]:
                raise ValueError("active observer input differs from independent stock probe")
            packed(manifest[s],out/"runs/record"/case/side/"native.tsv.gz")
            results.append(row)
    save(out/"comparison.json",results)
    shutil.copytree(args.tests,out/"checks",ignore=shutil.ignore_patterns("*.tsv","stdout","stderr","*.c"))
    for label in ("base","local","guard","loop_original","loop_renamed"):
        src = args.tests/label
        dest = out/"checks"/label
        for name in ("stdout","stderr","native.tsv","case.c"): packed(src/name,dest/(name+".gz"))
    for p in args.tests.glob("*.tsv"): packed(p,out/"checks"/(p.name+".gz"))
    if args.active_probe:
        extended_audit(out,args.active_probe)
    print(f"{len(results)} native comparisons, {save_index(out)} archived files")


if __name__ == "__main__":
    main()
