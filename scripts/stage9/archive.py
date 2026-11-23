"""Archive regular experiment outputs and encode the negative-test symlinks by value."""
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.stage8 import archive as codec

RUN_ROOTS=('formal','pilot','side','frontend','audit','build')
codec.ROOTS=(*RUN_ROOTS,'development')
codec.LOGS=('formal.log','regression.log','negative.log','details.log','pilot.log','acceptance.log','release-cli.log')


def pack(raw,dest,development=None):
    dest.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as temp:
        view=Path(temp)
        paths=[]
        for source,prefix in ((raw,Path()),(development,Path('development'))):
            if source is None:continue
            inside=[p for d in RUN_ROOTS for p in (source/d).rglob('*')]
            inside.extend(source/n for n in codec.LOGS if (source/n).is_file())
            paths.extend((p,prefix/p.relative_to(source)) for p in inside)
        for p,relative in paths:
            if '__pycache__' in relative.parts:continue
            if not p.is_file() and not p.is_symlink():continue
            assert codec.valid(relative.as_posix())
            out=view/relative
            out.parent.mkdir(parents=True,exist_ok=True)
            if p.is_symlink():
                if p.name!='alias.h' or p.readlink()!=Path('entry.h') or p.parent.name!='headers':
                    raise ValueError('Unexpected experiment symlink '+str(relative))
                out.with_name(out.name+'.symlink.json').write_text(json.dumps(dict(
                    link='entry.h',target_sha256=codec.sha(p.read_bytes())))+'\n')
            else:
                try:os.link(p,out)
                except OSError:shutil.copyfile(p,out)
        return codec.pack(view,dest)

def unpack(evidence,dest):
    return codec.unpack(evidence,dest,full=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('method',choices=['pack','unpack']);p.add_argument('source',type=Path);p.add_argument('dest',type=Path)
    p.add_argument('--development',type=Path,help='also retain the separate development measurements')
    a=p.parse_args()
    if a.method=='pack':pack(a.source.resolve(),a.dest.resolve(),a.development)
    else:unpack(a.source.resolve(),a.dest.resolve())
