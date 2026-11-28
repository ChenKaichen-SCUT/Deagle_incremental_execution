"""Incrementally build the SI-1B native solver in an independent copy of the frozen D native build tree."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RELEASE = "91a531d0c311f63de4a18f0aca443399ca7c817bfaf3bdcf5a6adfc3c299fc0a"
def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def build(native,out,jobs):
    native,out=native.resolve(),out.resolve()
    if native==out or native in out.parents or digest(native/"src/cbmc/deagle_exe")!=RELEASE:
        raise ValueError("need frozen native ELF and a separate destination")
    marker=out/".si1b-build"
    if not out.exists():
        shutil.copytree(native,out,symlinks=True)
        marker.write_text(RELEASE+"\n")
    elif not marker.is_file() or marker.read_text().strip()!=RELEASE:
        raise ValueError("unrecognized build directory")
    changed={}
    # The frozen build contains generated sources; keep them and its object files.
    for path in (ROOT/"src").rglob("*"):
        if not path.is_file() or path.suffix not in (".cpp",".h",".inc") and path.name!="Makefile":
            continue
        rel=path.relative_to(ROOT)
        data=path.read_bytes().replace(b"\r\n",b"\n")
        base=native/rel
        if base.is_file() and base.read_bytes().replace(b"\r\n",b"\n")==data:
            continue
        dest=out/rel
        if not dest.is_file() or dest.read_bytes()!=data:
            dest.parent.mkdir(exist_ok=True,parents=True);dest.write_bytes(data)
        changed[str(rel)]=hashlib.sha256(data).hexdigest()
    subprocess.run(["make","-C",str(out/"src"),"-j"+str(jobs),"cbmc.dir"],check=True)
    (out/"si1b-build.json").write_text(json.dumps(dict(base=RELEASE,elf=digest(out/"src/cbmc/deagle_exe"),sources=changed),indent=2)+"\n")
if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("native",type=Path);p.add_argument("output",type=Path);p.add_argument("--jobs",type=int,default=9)
    a=p.parse_args();build(a.native,a.output,a.jobs)
