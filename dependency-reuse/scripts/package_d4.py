"""Publish human-readable D4 tables next to the lossless original run archive."""
import argparse
import csv
import json
import shutil
from pathlib import Path

from diff_d1 import digest
from package_d1 import logical
from run_stock import save
from d4_archive import pack, read


def copy(src,dest):
    dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dest)


def table(path,fields,records):
    with path.open("w",newline="") as f:
        out=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n")
        out.writeheader();out.writerows(records)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ("runs","audit","new_directory"):p.add_argument(n,type=Path)
    p.add_argument("extra_raw",nargs="*",metavar="LABEL=PATH")
    a=p.parse_args();runs,audit,d=[x.resolve() for x in (a.runs,a.audit,a.new_directory)]
    d.mkdir(parents=True,exist_ok=False)
    for f in ("summary.json","plan.json"):copy(runs/f,d/f)
    copy(audit/"audit.json",d/"audit.json")
    stats=json.loads((audit/"audit.json").read_text());arms=json.loads((runs/"summary.json").read_text())
    times=[];uses=[];properties={}
    for case,modes in arms.items():
        dest=d/"pairs"/case
        for mode,info in modes.items():
            for version,m in info.items():
                if version not in ("P0","P1"):continue
                clock=m["search_ns"];origin=mode
                if mode=="stock" and version=="P1":
                    clock=modes["stock-search-observer"]["P1"]["search_ns"];origin="stock-search-observer"
                row=dict(case=case,mode=mode,version=version,search_s=clock/1e9 if clock is not None else "",
                    clock_source=origin if clock is not None else "",wall_s=m["wall_s"],cycle_s=info.get("cycle_s",""),
                    rss_kib=m["peak_rss_kib"],property_decider_s=m["property_decider_s"],status=m["verifier_status"],**m["counts"])
                times.append(row)
        properties[case]={}
        for version in ("P0","P1"):
            v=json.loads((runs/case/"stock"/version/"result.json").read_text())
            properties[case][version]=logical({k:v[k] for k in ("properties","classification","cProverStatus","target_status","unwinding_property_ids",
                "unwinding_iterations","unwinding_stop_or_warning","enabled_unwinding_assertions","vcc_messages","warnings","adapter_query_count")})
        for f in ("ready.tsv","imports.tsv","hits.tsv","selection.tsv","import-time.tsv","delta.json"):
            copy(runs/case/"reuse/P1/native"/f,dest/f)
        for f in (audit/case/"reuse").glob("witness-*.json"):copy(f,dest/f.name)
        for family,c in stats[case]["reuse"]["families"].items():
            uses.append(dict(case=case,family=family,**{k:c.get(k,0) for k in ("candidates","attached","root_unit","root_satisfied",
                "root_conflict","duplicate_batch","duplicate_resident","tautology","watch_unit","watch_conflict","analyze","minimize",
                "rows_used","rows_moved","rows_removed","root_false_removed")}))
    table(d/"timings.tsv",list(times[0]),times);table(d/"usage.tsv",list(uses[0]),uses);save(d/"properties.json",properties)
    pack(d/"raw",["matrix="+str(runs),"replay="+str(audit),*a.extra_raw])
    read(d/"raw","",None)
    save(d/"sha256.json",{p.relative_to(d).as_posix():digest(p) for p in sorted(d.rglob("*")) if p.is_file()})
    print("evidence index",digest(d/"sha256.json"))


if __name__=="__main__":main()
