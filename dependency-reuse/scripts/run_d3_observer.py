import argparse
import json
from pathlib import Path
from run_stock import BASE,run,sha,save
from run_d1 import CASES

if __name__=="__main__":
    p=argparse.ArgumentParser(description="Observe each actual D1 conflict and theory reason at its SAT boundary")
    p.add_argument("binary",type=Path)
    p.add_argument("out",type=Path)
    a=p.parse_args()
    binary,out=a.binary.resolve(),a.out.resolve()
    out.mkdir(parents=True,exist_ok=False)
    specs=json.loads((BASE/"bench/manifest.json").read_text())
    h=sha(binary)
    save(out/"plan.json",dict(cases=CASES,side="P0",binary_sha256=h,serial=True))
    for c in CASES:run(binary,specs[c],c,"P0",out/c,h)
