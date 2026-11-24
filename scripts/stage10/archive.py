"""Lossless stage 10 evidence: content-addressed native inputs, complete search traces, models and measurements."""
import argparse
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.stage8 import archive as codec

codec.ROOTS=('final','acceptance','pilot','build','failures')
codec.LOGS=('build-console.log','pilot.log','formal.log','final.log','stop.json')
def pack(raw,dest):
    # Native binaries are reproduced from locked code and hashes, not experiment data.
    import os
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        view=Path(tmp)
        names=[p for n in codec.ROOTS for p in (raw/n).rglob('*') if p.is_file()]
        names.extend(raw/n for n in codec.LOGS if (raw/n).is_file())
        for p in names:
            if p.name in ('solver-session','measurement.lock') or '__pycache__' in p.parts:continue
            assert not p.is_symlink()
            rel=p.relative_to(raw);out=view/rel;out.parent.mkdir(parents=True,exist_ok=True)
            try:os.link(p,out)
            except OSError:shutil.copyfile(p,out)
        return codec.pack(view,dest)
def unpack(evidence,dest):
    return codec.unpack(evidence,dest,full=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('op',choices=['pack','unpack']);p.add_argument('source',type=Path);p.add_argument('dest',type=Path)
    a=p.parse_args();(pack if a.op=='pack' else unpack)(a.source.resolve(),a.dest.resolve())
