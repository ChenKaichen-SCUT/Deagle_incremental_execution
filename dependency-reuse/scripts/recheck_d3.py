"""Restore one archived D3 process and repeat both full independent checks."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from prepare_d2 import prepare
from prepare_d3 import facts
from recheck_d2 import restore
from run_stock import BASE
from verify_d3_boundary import verify


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("checker",type=Path)
    p.add_argument("case")
    p.add_argument("new_directory",type=Path)
    p.add_argument("--mode",choices=("mixed","joint"),default="mixed")
    p.add_argument("--repeat",type=int,choices=(1,2,3),default=1)
    p.add_argument("--evidence",type=Path,default=BASE/"reports/evidence/d3")
    a=p.parse_args()
    ev=a.evidence.resolve();pair=ev/"pairs"/a.case
    r=next(z for z in json.loads((pair/"runs.json").read_text()) if (z["mode"],z["repeat"])==(a.mode,a.repeat))
    out=a.new_directory.resolve()
    out.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryDirectory() as name:
        tmp=Path(name)
        restore(ev,a.case,r,tmp/"proof")
        for f in ("native-learns.tsv","native-theory.tsv"):
            with gzip.open(pair/(f+".gz"),"rb") as src,(tmp/f).open("wb") as dst:shutil.copyfileobj(src,dst)
        assert verify(tmp/"proof",tmp/"native-theory.tsv")==r["checked_native_boundaries"]
        d1=BASE/"reports/evidence/d1"
        for scope in ("frozen","improved"):
            delta=pair/"delta" if scope=="improved" else d1/"pairs"/a.case
            manifest=pair/"P0-native.tsv.gz" if scope=="improved" else d1/"runs/record"/a.case/"P0/native.tsv.gz"
            dest=tmp/scope
            prepare(a.case,dest,pair=delta,native=manifest)
            facts(manifest,delta,dest/"declarations.txt")
            result=out/scope;result.mkdir()
            subprocess.run([a.checker.resolve(),tmp/"proof",dest/"inputs.txt",dest/"mapped.txt",tmp/"native-learns.tsv",
                            dest/"declarations.txt",result],check=True)
            for f,h in r[scope+"_hashes"].items():
                if hashlib.sha256((result/f).read_bytes()).hexdigest()!=h:raise ValueError(f+" hash mismatch")
            measured={k:int(n) for k,n in (l.split() for l in (result/"metrics.tsv").read_text().splitlines())}
            if measured!=r[scope]:raise ValueError("metrics differ from archived run")
    print(a.case,a.mode,a.repeat,r["raw_sha256"],"verified")
